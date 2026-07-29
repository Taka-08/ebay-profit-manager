from __future__ import annotations

import gc
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from platform_config import (
    FEE_MODE_AMOUNT,
    FEE_MODE_RATE,
    PLATFORM_IPHONE_RESALE,
    PLATFORM_MERCARI,
    calculate_simple_profit,
)
from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFIT_APP = PROJECT_ROOT / "streamlit_app.py"
MANAGER_APP = PROJECT_ROOT / "ebay_listing_manager" / "streamlit_app.py"


class PlatformProfitModeTest(unittest.TestCase):
    @staticmethod
    def element_with_label(elements, label: str):
        return next(element for element in elements if element.label == label)

    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="platform-profit-test-"))
        self.previous_workspace = os.environ.get("EBAY_TOOL_WORKSPACE")
        self.previous_db = os.environ.get("EBAY_LISTING_DB_PATH")
        os.environ["EBAY_TOOL_WORKSPACE"] = str(self.workspace)
        os.environ.pop("EBAY_LISTING_DB_PATH", None)

    def tearDown(self) -> None:
        if self.previous_workspace is None:
            os.environ.pop("EBAY_TOOL_WORKSPACE", None)
        else:
            os.environ["EBAY_TOOL_WORKSPACE"] = self.previous_workspace
        if self.previous_db is None:
            os.environ.pop("EBAY_LISTING_DB_PATH", None)
        else:
            os.environ["EBAY_LISTING_DB_PATH"] = self.previous_db
        gc.collect()
        shutil.rmtree(self.workspace, ignore_errors=True)

    def test_simple_profit_formulas(self) -> None:
        mercari = calculate_simple_profit(
            platform=PLATFORM_MERCARI,
            sale_price_yen=10000,
            purchase_price_yen=6000,
            fee_mode=FEE_MODE_RATE,
            fee_rate_percent=10,
            fee_amount_yen=0,
            shipping_yen=500,
            other_cost_yen=200,
        )
        self.assertEqual(1000, mercari.sales_fee_yen)
        self.assertEqual(2300, mercari.profit_yen)
        self.assertEqual(23, mercari.profit_margin)

        iphone = calculate_simple_profit(
            platform=PLATFORM_IPHONE_RESALE,
            sale_price_yen=80000,
            purchase_price_yen=50000,
            fee_mode=FEE_MODE_AMOUNT,
            fee_rate_percent=0,
            fee_amount_yen=8000,
            shipping_yen=1000,
            repair_cost_yen=3000,
            parts_cost_yen=2000,
            other_cost_yen=500,
        )
        self.assertEqual(0, iphone.sales_fee_yen)
        self.assertEqual(29000, iphone.profit_yen)
        self.assertAlmostEqual(36.25, iphone.profit_margin)

    def test_platform_switch_registration_and_manager_filter(self) -> None:
        profit = AppTest.from_file(str(PROFIT_APP)).run(timeout=60)
        self.assertEqual([], list(profit.exception))

        platform_radio = self.element_with_label(
            profit.radio,
            "販売プラットフォーム",
        )
        platform_radio.set_value(PLATFORM_MERCARI)
        profit.run(timeout=60)
        self.assertEqual([], list(profit.exception))
        self.assertFalse(
            any(item.label == "実重量（g）" for item in profit.number_input)
        )
        self.assertFalse(
            any(item.label == "現在のUSD/JPYレート" for item in profit.number_input)
        )

        self.element_with_label(profit.text_input, "商品名").set_value(
            "メルカリ連携テスト"
        )
        self.element_with_label(profit.text_input, "販売価格（円）").set_value(
            "10,000"
        )
        self.element_with_label(profit.text_input, "仕入れ価格（円）").set_value(
            "10,000"
        )
        self.element_with_label(
            profit.number_input,
            "販売手数料率（%）",
        ).set_value(10.0)
        self.element_with_label(profit.text_input, "送料（円）").set_value(
            "500"
        )
        self.element_with_label(profit.text_input, "その他経費（円）").set_value(
            "200"
        )
        profit.run(timeout=60)
        self.assertEqual([], list(profit.exception))

        self.element_with_label(
            profit.button,
            "出品管理ツールへ登録",
        ).click()
        profit.run(timeout=60)
        self.assertEqual([], list(profit.exception))
        self.assertTrue(any("保存ID" in item.value for item in profit.success))

        database = self.workspace / "ebay_listing_manager" / "ebay_listings.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            row = connection.execute(
                """
                SELECT platform, listing_price, purchase_price_yen,
                       sales_fee_input_mode, sales_fee_rate, sales_fee_yen,
                       simple_shipping_yen, other_cost_yen, expected_profit_yen,
                       profit_margin
                FROM listings
                """
            ).fetchone()
        self.assertEqual(PLATFORM_MERCARI, row[0])
        self.assertEqual(10000, row[1])
        self.assertEqual(10000, row[2])
        self.assertEqual(FEE_MODE_RATE, row[3])
        self.assertEqual(10, row[4])
        self.assertEqual(1000, row[5])
        self.assertEqual(500, row[6])
        self.assertEqual(200, row[7])
        self.assertEqual(-1700, row[8])
        self.assertEqual(-17, row[9])

        with closing(sqlite3.connect(database)) as connection:
            connection.execute(
                """
                UPDATE listings
                SET expected_shipping_carrier = ?,
                    expected_shipping_service = ?,
                    shipping_carrier = ?,
                    shipping_service = ?
                """,
                ("日本郵便", "小形包装物", "日本郵便", "小形包装物"),
            )
            connection.commit()

        manager = AppTest.from_file(str(MANAGER_APP)).run(timeout=60)
        self.assertEqual([], list(manager.exception))
        platform_filter = self.element_with_label(
            manager.selectbox,
            "販売プラットフォームで絞り込み",
        )
        self.assertIn(PLATFORM_MERCARI, platform_filter.options)
        self.assertIn(PLATFORM_IPHONE_RESALE, platform_filter.options)
        self.assertNotIn("その他", platform_filter.options)
        self.element_with_label(
            manager.number_input,
            "仕入価格（円）",
        ).set_value(12000.0)
        self.element_with_label(
            manager.button,
            "出品データを保存",
        ).click()
        manager.run(timeout=60)
        self.assertEqual([], list(manager.exception))
        with closing(sqlite3.connect(database)) as connection:
            saved = connection.execute(
                """
                SELECT purchase_price_yen, purchase_price,
                       expected_profit_yen, profit_margin
                FROM listings
                """
            ).fetchone()
        self.assertEqual((12000, 12000, -3700, -37), saved)
        self.assertEqual(
            12000,
            self.element_with_label(
                manager.number_input,
                "仕入価格（円）",
            ).value,
        )

        self.element_with_label(manager.selectbox, "ステータス").set_value(
            "売却済"
        )
        manager.run(timeout=60)
        self.assertEqual([], list(manager.exception))
        self.assertTrue(
            any(
                item.label == "実際の販売価格（円）"
                for item in manager.number_input
            )
        )
        shipping_carrier = self.element_with_label(
            manager.selectbox,
            "発送業者",
        )
        self.assertTrue(
            {
                "日本郵便",
                "SpeedPAK Economy",
                "FedEx",
                "DHL",
            }.issubset(set(shipping_carrier.options))
        )
        shipping_carrier.set_value("SpeedPAK Economy")
        manager.run(timeout=60)
        self.assertEqual([], list(manager.exception))
        self.assertEqual(
            "SpeedPAK Economy",
            self.element_with_label(
                manager.text_input,
                "実績配送サービス",
            ).value,
        )
        self.element_with_label(manager.button, "更新").click()
        manager.run(timeout=60)
        self.assertEqual([], list(manager.exception))
        with closing(sqlite3.connect(database)) as connection:
            sold_row = connection.execute(
                """
                SELECT status, actual_sales_fee_yen,
                       actual_shipping_yen, actual_purchase_price_yen,
                       actual_profit_yen, actual_profit_margin,
                       expected_shipping_carrier, expected_shipping_service,
                       shipping_carrier, shipping_service
                FROM listings
                """
            ).fetchone()
        self.assertEqual(
            (
                "売却済",
                1000,
                500,
                12000,
                -3700,
                -37,
                "日本郵便",
                "小形包装物",
                "SpeedPAK Economy",
                "SpeedPAK Economy",
            ),
            sold_row,
        )

        reloaded_manager = AppTest.from_file(str(MANAGER_APP)).run(timeout=60)
        self.assertEqual([], list(reloaded_manager.exception))
        self.assertEqual(
            12000,
            self.element_with_label(
                reloaded_manager.number_input,
                "仕入価格（円）",
            ).value,
        )

        self.element_with_label(
            reloaded_manager.number_input,
            "仕入価格（円）",
        ).set_value(13000.0)
        self.element_with_label(
            reloaded_manager.button,
            "出品データを保存",
        ).click()
        reloaded_manager.run(timeout=60)
        self.assertEqual([], list(reloaded_manager.exception))
        with closing(sqlite3.connect(database)) as connection:
            resaved = connection.execute(
                """
                SELECT purchase_price_yen, actual_purchase_price_yen,
                       expected_profit_yen, actual_profit_yen,
                       shipping_carrier, expected_shipping_carrier
                FROM listings
                """
            ).fetchone()
        self.assertEqual(
            (13000, 13000, -4700, -4700, "SpeedPAK Economy", "日本郵便"),
            resaved,
        )

        del profit
        del manager
        del reloaded_manager

    def test_iphone_mode_registers_platform_specific_fields(self) -> None:
        profit = AppTest.from_file(str(PROFIT_APP)).run(timeout=60)
        self.element_with_label(
            profit.radio,
            "販売プラットフォーム",
        ).set_value(PLATFORM_IPHONE_RESALE)
        profit.run(timeout=60)
        self.assertEqual([], list(profit.exception))
        self.assertTrue(
            any(item.label == "売却した業者" for item in profit.text_input)
        )
        self.assertTrue(any(item.label == "容量" for item in profit.text_input))
        self.assertFalse(
            any(item.label == "販売手数料の入力方法" for item in profit.radio)
        )
        self.assertFalse(
            any(item.label == "販売手数料（円）" for item in profit.text_input)
        )
        self.assertFalse(
            any(item.label == "その他経費（円）" for item in profit.text_input)
        )
        self.assertFalse(
            any(item.label == "修理費（円）" for item in profit.text_input)
        )
        self.assertFalse(
            any(item.label == "部品代（円）" for item in profit.text_input)
        )
        self.assertFalse(
            any(item.label == "配送先の国" for item in profit.selectbox)
        )

        self.element_with_label(profit.text_input, "商品名").set_value(
            "iPhone転売連携テスト"
        )
        self.element_with_label(profit.text_input, "売却した業者").set_value(
            "イオシス"
        )
        self.element_with_label(profit.text_input, "容量").set_value("256GB")
        self.element_with_label(profit.text_input, "売却価格（円）").set_value(
            "80,000"
        )
        self.element_with_label(profit.text_input, "仕入れ価格（円）").set_value(
            "50,000"
        )
        self.element_with_label(profit.text_input, "送料（円）").set_value(
            "1,000"
        )
        profit.run(timeout=60)
        self.element_with_label(
            profit.button,
            "出品管理ツールへ登録",
        ).click()
        profit.run(timeout=60)
        self.assertEqual([], list(profit.exception))

        database = self.workspace / "ebay_listing_manager" / "ebay_listings.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            row = connection.execute(
                """
                SELECT platform, iphone_model, iphone_capacity,
                       sales_fee_input_mode, sales_fee_yen,
                       repair_cost_yen, parts_cost_yen, other_cost_yen,
                       expected_profit_yen, profit_margin
                FROM listings
                """
            ).fetchone()
        self.assertEqual(
            (
                PLATFORM_IPHONE_RESALE,
                "イオシス",
                "256GB",
                FEE_MODE_AMOUNT,
                0,
                0,
                0,
                0,
                29000,
                36.25,
            ),
            row,
        )

        manager = AppTest.from_file(str(MANAGER_APP)).run(timeout=60)
        self.assertEqual([], list(manager.exception))
        self.assertTrue(
            any(item.label == "売却した業者" for item in manager.text_input)
        )
        self.assertTrue(
            any(item.label == "売却価格（円）" for item in manager.number_input)
        )
        self.assertFalse(
            any(item.label == "修理費（円）" for item in manager.number_input)
        )
        self.assertFalse(
            any(item.label == "部品代（円）" for item in manager.number_input)
        )
        self.element_with_label(manager.selectbox, "ステータス").set_value(
            "売却済"
        )
        manager.run(timeout=60)
        self.assertEqual([], list(manager.exception))
        self.assertTrue(
            any(
                item.label == "実際の売却価格（円）"
                for item in manager.number_input
            )
        )
        self.assertFalse(
            any(
                item.label == "実際の販売手数料（円）"
                for item in manager.number_input
            )
        )
        self.assertFalse(
            any(
                item.label == "実際のその他経費（円）"
                for item in manager.number_input
            )
        )
        self.element_with_label(manager.button, "更新").click()
        manager.run(timeout=60)
        self.assertEqual([], list(manager.exception))
        with closing(sqlite3.connect(database)) as connection:
            sold_row = connection.execute(
                """
                SELECT status, actual_sales_fee_yen,
                       actual_repair_cost_yen, actual_parts_cost_yen,
                       actual_shipping_yen, actual_profit_yen
                FROM listings
                """
            ).fetchone()
        self.assertEqual(("売却済", 0, 0, 0, 1000, 29000), sold_row)
        del manager
        del profit

    def test_legacy_other_platform_is_migrated(self) -> None:
        manager = AppTest.from_file(str(MANAGER_APP)).run(timeout=60)
        self.assertEqual([], list(manager.exception))
        database = self.workspace / "ebay_listing_manager" / "ebay_listings.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            now = "2026-07-25 12:00:00"
            connection.execute(
                """
                INSERT INTO listings (
                    product_name, platform, listing_date, status,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("旧その他データ", "その他", "2026-07-25", "出品中", now, now),
            )
            connection.commit()

        manager.run(timeout=60)
        self.assertEqual([], list(manager.exception))
        with closing(sqlite3.connect(database)) as connection:
            platform = connection.execute(
                "SELECT platform FROM listings WHERE product_name = ?",
                ("旧その他データ",),
            ).fetchone()[0]
        self.assertEqual(PLATFORM_IPHONE_RESALE, platform)
        del manager


if __name__ == "__main__":
    unittest.main()
