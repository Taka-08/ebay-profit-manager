from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack, closing
from pathlib import Path
from unittest.mock import patch

import ebay_listing_manager.streamlit_app as manager_app
import streamlit_app as profit_app
from currency_config import SUPPORTED_CURRENCIES, YAHOO_FINANCE_SYMBOLS
from streamlit.testing.v1 import AppTest


RATES = {
    "USD": 150.0,
    "CAD": 110.0,
    "GBP": 190.0,
    "AUD": 100.0,
}

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANAGER_APP = PROJECT_ROOT / "ebay_listing_manager" / "streamlit_app.py"


class MultiCurrencyTest(unittest.TestCase):
    @staticmethod
    def element_with_label(elements, label: str):
        return next(element for element in elements if element.label == label)

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(
            prefix="ebay-multi-currency-test-"
        )
        self.workspace = Path(self.temp_dir.name)
        self.manager_dir = self.workspace / "ebay_listing_manager"
        self.database = self.manager_dir / "ebay_listings.sqlite3"
        self.rate_file = self.manager_dir / "exchange_rate.json"
        self.event_file = self.manager_dir / "registration_event.json"
        self.log_file = self.manager_dir / "logs" / "registration.log"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def profit_path_patches(self) -> ExitStack:
        stack = ExitStack()
        stack.enter_context(patch.object(profit_app, "LISTING_DB_PATH", self.database))
        stack.enter_context(patch.object(profit_app, "LISTING_MANAGER_DIR", self.manager_dir))
        stack.enter_context(
            patch.object(profit_app, "SHARED_EXCHANGE_RATE_PATH", self.rate_file)
        )
        stack.enter_context(
            patch.object(profit_app, "REGISTRATION_EVENT_PATH", self.event_file)
        )
        stack.enter_context(
            patch.object(profit_app, "REGISTRATION_LOG_PATH", self.log_file)
        )
        stack.enter_context(
            patch.dict(
                os.environ,
                {"TURSO_DATABASE_URL": "", "TURSO_AUTH_TOKEN": ""},
                clear=False,
            )
        )
        return stack

    def test_primary_api_uses_each_currency_pair(self) -> None:
        def fake_request(url: str) -> dict[str, object]:
            symbol = next(
                symbol
                for symbol in sorted(
                    YAHOO_FINANCE_SYMBOLS.values(),
                    key=len,
                    reverse=True,
                )
                if url.endswith(symbol)
            )
            currency = next(
                code
                for code, configured_symbol in YAHOO_FINANCE_SYMBOLS.items()
                if configured_symbol == symbol
            )
            return {
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "symbol": symbol,
                                "currency": "JPY",
                                "regularMarketPrice": RATES[currency],
                                "regularMarketTime": 1785542400,
                            }
                        }
                    ],
                    "error": None,
                }
            }

        with patch.object(
            profit_app,
            "exchange_rate_request_json",
            side_effect=fake_request,
        ):
            for currency in SUPPORTED_CURRENCIES:
                with self.subTest(currency=currency):
                    result = profit_app.fetch_primary_exchange_rate(currency)
                    self.assertEqual(currency, result["currency_code"])
                    self.assertEqual(RATES[currency], result["rate"])

    def test_rate_store_preserves_all_currency_records(self) -> None:
        with self.profit_path_patches():
            for currency, rate in RATES.items():
                profit_app.save_shared_exchange_rate(
                    rate,
                    currency_code=currency,
                    source="test",
                    api_updated_at="2026-08-01T00:00:00+09:00",
                )
            for currency, rate in RATES.items():
                self.assertEqual(
                    rate,
                    profit_app.read_shared_exchange_rate(currency),
                )
            stored = json.loads(self.rate_file.read_text(encoding="utf-8"))
            self.assertEqual(set(SUPPORTED_CURRENCIES), set(stored["rates"]))
            self.assertEqual(RATES["USD"], stored["usd_jpy"])

    def test_registration_and_actual_profit_for_all_currencies(self) -> None:
        with self.profit_path_patches():
            for currency, rate in RATES.items():
                gross_sales_yen = 20.0 * rate
                planned_profit = (
                    gross_sales_yen
                    - 1000.0
                    - 20.0
                    - 30.0
                    - gross_sales_yen * 0.15
                    - gross_sales_yen * 0.02
                    - gross_sales_yen * 0.021
                    - 0.30 * RATES["USD"]
                    - 50.0
                    - 500.0
                )
                inputs = profit_app.ProductInputs(
                    product_name=f"{currency}商品",
                    sku=f"SKU-{currency}",
                    sale_price_usd=20.0,
                    buyer_shipping_usd=0.0,
                    purchase_price_yen=1000.0,
                    domestic_shipping_yen=20.0,
                    packaging_yen=30.0,
                    destination_country="アメリカ",
                    weight_g=500.0,
                    length_cm=0.0,
                    width_cm=0.0,
                    height_cm=0.0,
                    ebay_fee_rate=15.0,
                    overseas_fee_rate=2.0,
                    ad_rate=2.1,
                    other_fee_yen=50.0,
                    fixed_fee_usd=0.30,
                    target_profit_yen=0.0,
                    product_url="",
                    source_url="",
                    exchange_rate=rate,
                    currency_code=currency,
                    usd_jpy_rate=RATES["USD"],
                )
                shipping = profit_app.ShippingResult(
                    result_id=f"test::{currency}",
                    carrier="Test Carrier",
                    service="Test Service",
                    actual_weight_g=500.0,
                    volumetric_weight_g=None,
                    applied_weight_g=500.0,
                    billing_weight_g=500.0,
                    base_shipping_yen=500.0,
                    fuel_surcharge_yen=0.0,
                    surcharge_yen=0.0,
                    additional_fee_yen=0.0,
                    other_additional_fee_yen=0.0,
                    total_shipping_yen=500.0,
                    profit_yen=planned_profit,
                    profit_margin=planned_profit / gross_sales_yen * 100,
                    shippable=True,
                    status="発送可能",
                    reason="",
                    calculation_mode="実重量のみの概算",
                    note="",
                )
                outcome = profit_app.register_listing(inputs, shipping)
                self.assertTrue(outcome.success, outcome.error)

            with closing(sqlite3.connect(self.database)) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    "SELECT * FROM listings ORDER BY id"
                ).fetchall()

        self.assertEqual(4, len(rows))
        for row_source in rows:
            row = dict(row_source)
            currency = row["currency_code"]
            rate = RATES[currency]
            self.assertEqual(rate, row["exchange_rate"])
            self.assertEqual(RATES["USD"], row["usd_jpy_rate"])
            self.assertEqual(20.0 * rate, row["sale_price_yen"])

            order_revenue = manager_app.calculate_order_revenue_yen(
                rate,
                20.0,
                10.0,
                2.0,
                1.0,
                0.30,
                RATES["USD"],
            )
            expected_order_revenue = 30.0 * rate - 3.30 * RATES["USD"]
            self.assertAlmostEqual(expected_order_revenue, order_revenue)

            actual_costs = {
                "actual_purchase_price_yen": 1000.0,
                "actual_overseas_fee_yen": 100.0,
                "actual_copy_cost_yen": 20.0,
                "actual_packaging_yen": 30.0,
                "actual_other_cost_yen": 50.0,
            }
            actual_profit = manager_app.calculate_actual_profit(
                row,
                rate,
                20.0,
                10.0,
                2.0,
                1.0,
                0.30,
                RATES["USD"],
                2000.0,
                actual_costs,
            )
            self.assertAlmostEqual(
                expected_order_revenue - 1000.0 - 2000.0 - 100.0 - 20.0 - 30.0 - 50.0,
                actual_profit,
            )

        gbp_id = next(
            int(row["id"])
            for row in map(dict, rows)
            if row["currency_code"] == "GBP"
        )
        with patch.dict(
            os.environ,
            {
                "EBAY_TOOL_WORKSPACE": str(self.workspace),
                "EBAY_LISTING_DB_PATH": str(self.database),
                "TURSO_DATABASE_URL": "",
                "TURSO_AUTH_TOKEN": "",
            },
            clear=False,
        ):
            manager = AppTest.from_file(str(MANAGER_APP)).run(timeout=60)
            self.assertEqual([], list(manager.exception))
            self.element_with_label(
                manager.selectbox,
                "管理する出品",
            ).set_value(gbp_id)
            manager.run(timeout=60)
            self.element_with_label(manager.selectbox, "ステータス").set_value(
                manager_app.STATUS_SOLD
            )
            manager.run(timeout=60)
            self.assertEqual([], list(manager.exception))

            self.element_with_label(
                manager.number_input,
                "実際の販売価格（GBP / £）",
            ).set_value(20.0)
            self.element_with_label(
                manager.number_input,
                "購入者から受け取った送料（GBP / £）",
            ).set_value(10.0)
            self.element_with_label(
                manager.number_input,
                "実績為替レート（GBP/JPY）",
            ).set_value(RATES["GBP"])
            self.element_with_label(
                manager.number_input,
                "手数料換算用USD/JPY実績レート",
            ).set_value(RATES["USD"])
            self.element_with_label(
                manager.number_input,
                "eBay取引手数料（USD）",
            ).set_value(2.0)
            self.element_with_label(
                manager.number_input,
                "一般広告料 / Promoted Listings広告料（USD）",
            ).set_value(1.0)
            self.element_with_label(
                manager.number_input,
                "固定手数料（USD）",
            ).set_value(0.30)
            self.element_with_label(
                manager.number_input,
                "実際の送料（円）",
            ).set_value(2000.0)
            manager.run(timeout=60)
            self.assertEqual([], list(manager.exception))
            order_revenue_input = self.element_with_label(
                manager.number_input,
                "注文の収益（円）",
            )
            self.assertEqual(5205.0, order_revenue_input.value)
            self.assertTrue(
                any(
                    "注文の収益（USD）: $34.70" in caption.value
                    for caption in manager.caption
                )
            )

            order_revenue_input.set_value(5000.0)
            manager.run(timeout=60)
            self.assertEqual([], list(manager.exception))
            self.assertTrue(
                any(
                    "注文の収益（USD）: $33.33" in caption.value
                    for caption in manager.caption
                )
            )

            self.element_with_label(manager.button, "更新").click()
            manager.run(timeout=60)
            self.assertEqual([], list(manager.exception))

        with closing(sqlite3.connect(self.database)) as connection:
            actual = connection.execute(
                """
                SELECT status, currency_code, actual_sale_price_usd,
                       actual_buyer_shipping_usd, actual_exchange_rate,
                       actual_usd_jpy_rate, actual_fee_schema_version,
                       actual_order_revenue_yen,
                       actual_overseas_fee_yen, actual_profit_yen,
                       actual_profit_margin
                FROM listings
                WHERE id = ?
                """,
                (gbp_id,),
            ).fetchone()
        self.assertEqual(manager_app.STATUS_SOLD, actual[0])
        self.assertEqual("GBP", actual[1])
        self.assertEqual(20.0, actual[2])
        self.assertEqual(10.0, actual[3])
        self.assertEqual(RATES["GBP"], actual[4])
        self.assertEqual(RATES["USD"], actual[5])
        self.assertEqual(manager_app.ACTUAL_FEE_SCHEMA_SEPARATE, actual[6])
        self.assertEqual(5000.0, actual[7])
        expected_actual_profit = (
            5000.0 - 1000.0 - 2000.0 - 20.0 - 30.0 - 50.0 - actual[8]
        )
        self.assertEqual(expected_actual_profit, actual[9])
        self.assertAlmostEqual(expected_actual_profit / 5700.0 * 100, actual[10])

        with closing(sqlite3.connect(self.database)) as connection:
            connection.row_factory = sqlite3.Row
            sold_row = dict(
                connection.execute(
                    "SELECT * FROM listings WHERE id = ?",
                    (gbp_id,),
                ).fetchone()
            )
        aggregate = manager_app.aggregate_rows([sold_row])
        self.assertEqual(5700.0, aggregate["売上合計"])
        self.assertEqual(300.0, aggregate["eBay取引手数料合計"])
        self.assertEqual(150.0, aggregate["広告費合計"])
        self.assertEqual(45.0, aggregate["固定手数料合計"])
        self.assertEqual(expected_actual_profit, aggregate["実利益合計"])

    def test_order_revenue_usd_uses_actual_usd_jpy_rate(self) -> None:
        self.assertAlmostEqual(
            16.7534942821,
            manager_app.calculate_order_revenue_usd(2637.0, 157.40),
        )
        self.assertIsNone(manager_app.calculate_order_revenue_usd(2637.0, 0.0))

    def test_legacy_row_is_kept_and_defaults_to_usd(self) -> None:
        self.manager_dir.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                """
                CREATE TABLE listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_name TEXT NOT NULL,
                    listing_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO listings (
                    product_name, listing_date, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "既存USD商品",
                    "2026-08-01",
                    "出品中",
                    "2026-08-01 00:00:00",
                    "2026-08-01 00:00:00",
                ),
            )
            connection.commit()

        with patch.object(manager_app, "DB_PATH", self.database), patch.dict(
            os.environ,
            {"TURSO_DATABASE_URL": "", "TURSO_AUTH_TOKEN": ""},
            clear=False,
        ):
            manager_app.init_db()

        with closing(sqlite3.connect(self.database)) as connection:
            row = connection.execute(
                """
                SELECT product_name, currency_code, actual_fee_schema_version
                FROM listings
                """
            ).fetchone()
        self.assertEqual(
            (
                "既存USD商品",
                "USD",
                manager_app.ACTUAL_FEE_SCHEMA_LEGACY,
            ),
            row,
        )
        self.assertAlmostEqual(
            2.0,
            manager_app.actual_transaction_fee_usd(
                {
                    "actual_ebay_fee_usd": 2.30,
                    "actual_fixed_fee_usd": 0.30,
                    "actual_fee_schema_version": manager_app.ACTUAL_FEE_SCHEMA_LEGACY,
                }
            ),
        )
        self.assertEqual(
            2.30,
            manager_app.actual_transaction_fee_usd(
                {
                    "actual_ebay_fee_usd": 2.30,
                    "actual_fixed_fee_usd": 0.30,
                    "actual_fee_schema_version": manager_app.ACTUAL_FEE_SCHEMA_SEPARATE,
                }
            ),
        )


if __name__ == "__main__":
    unittest.main()
