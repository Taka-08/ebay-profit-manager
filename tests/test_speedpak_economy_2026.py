from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import streamlit_app as app
from destination_countries import (
    COUNTRY_BY_CODE,
    EU27_COUNTRY_CODES,
    normalize_destination_country,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RATE_BOOK_PATH = PROJECT_ROOT / "shipping_rates.json"
PROFIT_APP_PATH = PROJECT_ROOT / "streamlit_app.py"


def product_inputs(
    country: str,
    *,
    sale_price: float = 100.0,
    exchange_rate: float = 100.0,
    eur_jpy_rate: float = 100.0,
    weight_g: float = 500.0,
    length_cm: float = 0.0,
    width_cm: float = 0.0,
    height_cm: float = 0.0,
    postal_code: str = "",
    currency_code: str = "USD",
    us_tariff_rule_date: str = "",
) -> app.ProductInputs:
    return app.ProductInputs(
        product_name="SpeedPAK Economy test",
        sku="",
        sale_price_usd=sale_price,
        buyer_shipping_usd=0.0,
        purchase_price_yen=0.0,
        domestic_shipping_yen=0.0,
        packaging_yen=0.0,
        destination_country=country,
        weight_g=weight_g,
        length_cm=length_cm,
        width_cm=width_cm,
        height_cm=height_cm,
        ebay_fee_rate=0.0,
        overseas_fee_rate=0.0,
        ad_rate=0.0,
        other_fee_yen=0.0,
        fixed_fee_usd=0.0,
        target_profit_yen=0.0,
        product_url="",
        source_url="",
        exchange_rate=exchange_rate,
        postal_code=postal_code,
        currency_code=currency_code,
        usd_jpy_rate=exchange_rate,
        eur_jpy_rate=eur_jpy_rate,
        us_tariff_rule_date=us_tariff_rule_date,
    )


class SpeedpakEconomy2026Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rate_book = json.loads(RATE_BOOK_PATH.read_text(encoding="utf-8"))
        cls.service = next(
            service
            for service in cls.rate_book["services"]
            if service["service"] == "SpeedPAK Economy"
        )

    def result(self, country: str, **kwargs: float) -> app.ShippingResult:
        return app.calculate_one_shipping_result(
            self.service,
            product_inputs(country, **kwargs),
        )

    def test_all_eu27_aliases_normalize_to_iso2(self) -> None:
        self.assertEqual(27, len(EU27_COUNTRY_CODES))
        for code in EU27_COUNTRY_CODES:
            country = COUNTRY_BY_CODE[code]
            with self.subTest(code=code):
                self.assertEqual(code, normalize_destination_country(code))
                self.assertEqual(code, normalize_destination_country(country.english_name))
                self.assertEqual(code, normalize_destination_country(country.japanese_name))

        self.assertEqual("US", normalize_destination_country("アメリカ"))
        self.assertEqual("US", normalize_destination_country("United States"))
        self.assertEqual("GB", normalize_destination_country("イギリス"))
        self.assertEqual("AU", normalize_destination_country("Australia"))

    def test_eu_destination_widget_applies_pending_eur_rate_before_render(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="speedpak-eu-ui-test-"))
        with patch.dict(
            os.environ,
            {
                "EBAY_TOOL_WORKSPACE": str(workspace),
                "TURSO_DATABASE_URL": "",
                "TURSO_AUTH_TOKEN": "",
            },
            clear=False,
        ):
            ui = AppTest.from_file(str(PROFIT_APP_PATH)).run(timeout=30)
            ui.session_state["eur_jpy_reference_rate"] = 170.0
            ui.session_state["eur_jpy_reference_source"] = "test"
            ui.session_state["eur_jpy_reference_updated_at"] = "2026-08-02T00:00:00+09:00"
            ui.session_state["pending_eur_jpy_rate"] = 171.2345
            next(item for item in ui.selectbox if item.label == "配送先の国").set_value("FR")
            ui.run(timeout=30)

        self.assertFalse(ui.exception)
        self.assertEqual(
            171.2345,
            next(
                item
                for item in ui.number_input
                if item.label == "商品価値判定用 EUR/JPYレート"
            ).value,
        )

    def test_pdf_rate_counts_and_effective_date(self) -> None:
        counts = self.rate_book["metadata"]["orange"]["rate_rows_by_zone"]
        self.assertEqual("2026-07-30", self.service["effective_from"])
        self.assertEqual("orange-connex-economy-japan-2026-07-30", self.service["rate_book_version"])
        self.assertEqual(2261, len(self.service["rates"]))
        self.assertEqual(66, counts["DE"])
        self.assertEqual(56, counts["SE"])
        for code in set(EU27_COUNTRY_CODES) - {"DE", "SE"}:
            self.assertEqual(76, counts[code])
        self.assertTrue(set(EU27_COUNTRY_CODES).issubset(app.DEFAULT_COUNTRIES))

    def test_country_specific_pdf_rates_are_not_reused(self) -> None:
        expected_500g = {
            "AT": 3242,
            "BE": 3395,
            "BG": 3214,
            "CY": 5552,
            "CZ": 3350,
            "DK": 3282,
            "EE": 3876,
            "ES": 3042,
            "FI": 4104,
            "FR": 3356,
            "GR": 3395,
            "HR": 3614,
            "HU": 3137,
            "IE": 3385,
            "IT": 3253,
            "LT": 3206,
            "LU": 3100,
            "LV": 3543,
            "MT": 5070,
            "NL": 3172,
            "PL": 2920,
            "PT": 2974,
            "RO": 3062,
            "SK": 3521,
            "SI": 3566,
            "SE": 2669,
            "DE": 2411,
        }
        self.assertEqual(set(EU27_COUNTRY_CODES), set(expected_500g))
        for code, expected_yen in expected_500g.items():
            with self.subTest(code=code):
                result = self.result(code, weight_g=500)
                self.assertTrue(result.shippable)
                self.assertEqual(expected_yen, result.base_shipping_yen)
                self.assertEqual(code, result.zone)

    def test_new_registration_snapshot_contains_rate_book_identity(self) -> None:
        result = self.result("FR", weight_g=500)
        payload = app.shipping_breakdown_payload(result, "2026-08-02T00:00:00+09:00")
        self.assertEqual("2026-07-30", payload["effective_from"])
        self.assertEqual(
            "orange-connex-economy-japan-2026-07-30",
            payload["rate_book_version"],
        )
        self.assertEqual([12], payload["source_pages"])

    def test_country_weight_limits(self) -> None:
        for code in EU27_COUNTRY_CODES:
            allowed = 25000 if code == "DE" else 20000 if code == "SE" else 30000
            rejected = allowed + 1
            with self.subTest(code=code):
                self.assertTrue(self.result(code, weight_g=allowed).shippable)
                self.assertFalse(self.result(code, weight_g=rejected).shippable)

    def test_every_eu_weight_boundary_selects_its_own_pdf_row(self) -> None:
        for code in EU27_COUNTRY_CODES:
            rows = sorted(
                (row for row in self.service["rates"] if row["zone"] == code),
                key=lambda row: row["max_weight_g"],
            )
            for index, row in enumerate(rows):
                with self.subTest(code=code, boundary=row["max_weight_g"]):
                    exact = self.result(code, weight_g=float(row["max_weight_g"]))
                    self.assertTrue(exact.shippable)
                    self.assertEqual(row["base_shipping_yen"], exact.base_shipping_yen)
                    if index > 0:
                        just_above_previous = self.result(
                            code,
                            weight_g=float(rows[index - 1]["max_weight_g"]) + 1,
                        )
                        self.assertEqual(
                            row["base_shipping_yen"],
                            just_above_previous.base_shipping_yen,
                        )

    def test_country_size_and_volume_limits(self) -> None:
        for code in EU27_COUNTRY_CODES:
            width_limit = 60 if code == "DE" else 40
            height_limit = 60 if code == "DE" else 40
            with self.subTest(code=code, limit="allowed"):
                self.assertTrue(
                    self.result(
                        code,
                        weight_g=1000,
                        length_cm=120,
                        width_cm=width_limit,
                        height_cm=1,
                    ).shippable
                )
            with self.subTest(code=code, limit="width"):
                self.assertFalse(
                    self.result(
                        code,
                        weight_g=1000,
                        length_cm=100,
                        width_cm=width_limit + 1,
                        height_cm=1,
                    ).shippable
                )
            with self.subTest(code=code, limit="height"):
                self.assertTrue(
                    self.result(
                        code,
                        weight_g=1000,
                        length_cm=100,
                        width_cm=1,
                        height_cm=height_limit,
                    ).shippable
                )
                self.assertFalse(
                    self.result(
                        code,
                        weight_g=1000,
                        length_cm=100,
                        width_cm=1,
                        height_cm=height_limit + 1,
                    ).shippable
                )
            with self.subTest(code=code, limit="length"):
                self.assertFalse(
                    self.result(
                        code,
                        weight_g=1000,
                        length_cm=121,
                        width_cm=1,
                        height_cm=1,
                    ).shippable
                )
            volume_boundary = (100, 60, 30) if code == "DE" else (120, 40, 37.5)
            with self.subTest(code=code, limit="volume"):
                self.assertIsNone(
                    app.size_limit_reason(
                        self.service,
                        product_inputs(
                            code,
                            weight_g=1000,
                            length_cm=volume_boundary[0],
                            width_cm=volume_boundary[1],
                            height_cm=volume_boundary[2],
                        ),
                        code,
                    )
                )
                self.assertIsNotNone(
                    app.size_limit_reason(
                        self.service,
                        product_inputs(
                            code,
                            weight_g=1000,
                            length_cm=volume_boundary[0],
                            width_cm=volume_boundary[1],
                            height_cm=volume_boundary[2] + 0.1,
                        ),
                        code,
                    )
                )

    def test_volumetric_weight_uses_divisor_8000_and_greater_weight(self) -> None:
        result = self.result(
            "FR",
            weight_g=5000,
            length_cm=80,
            width_cm=40,
            height_cm=25,
        )
        self.assertTrue(result.shippable)
        self.assertEqual(10000, result.volumetric_weight_g)
        self.assertEqual(10000, result.applied_weight_g)
        self.assertEqual(10000, result.billing_weight_g)
        self.assertEqual(29226, result.base_shipping_yen)

        actual_is_greater = self.result(
            "FR",
            weight_g=5000,
            length_cm=20,
            width_cm=20,
            height_cm=20,
        )
        self.assertEqual(1000, actual_is_greater.volumetric_weight_g)
        self.assertEqual(5000, actual_is_greater.applied_weight_g)
        self.assertEqual(5000, actual_is_greater.billing_weight_g)

    def test_eu_product_value_limit(self) -> None:
        at_limit = self.result(
            "FR",
            sale_price=150,
            exchange_rate=100,
            eur_jpy_rate=100,
        )
        over_limit = self.result(
            "FR",
            sale_price=150.01,
            exchange_rate=100,
            eur_jpy_rate=100,
        )
        unknown_rate = self.result(
            "FR",
            sale_price=1000,
            exchange_rate=100,
            eur_jpy_rate=0,
        )
        self.assertTrue(at_limit.shippable)
        self.assertFalse(over_limit.shippable)
        self.assertIn("150 EUR", over_limit.reason)
        self.assertTrue(unknown_rate.shippable)
        self.assertIn("EUR", unknown_rate.note)

        gbp_at_limit = self.result(
            "FR",
            sale_price=180,
            exchange_rate=150,
            eur_jpy_rate=180,
            currency_code="GBP",
        )
        gbp_over_limit = self.result(
            "FR",
            sale_price=180.01,
            exchange_rate=150,
            eur_jpy_rate=180,
            currency_code="GBP",
        )
        self.assertTrue(gbp_at_limit.shippable)
        self.assertFalse(gbp_over_limit.shippable)

    def test_japanese_english_and_iso_inputs_choose_same_rate(self) -> None:
        rates = {
            self.result(country, weight_g=500).base_shipping_yen
            for country in ("フランス", "France", "FR")
        }
        self.assertEqual({3356}, rates)

    def test_latest_us_uk_au_and_de_pdf_rates_and_boundaries(self) -> None:
        zones = {
            "US_MAINLAND": ("US", "10001", 66, 1215, 40556),
            "US_NON_MAINLAND": ("US", "96801", 46, 1287, 27883),
            "UK": ("GB", "", 66, 929, 37046),
            "AU": ("AU", "", 61, 1131, 15615),
            "DE": ("DE", "", 66, 1512, 70047),
        }
        for zone, (country, postal_code, count, first_price, last_price) in zones.items():
            rows = sorted(
                (row for row in self.service["rates"] if row["zone"] == zone),
                key=lambda row: row["max_weight_g"],
            )
            with self.subTest(zone=zone):
                self.assertEqual(count, len(rows))
                self.assertEqual(first_price, rows[0]["base_shipping_yen"])
                self.assertEqual(last_price, rows[-1]["base_shipping_yen"])
                first = self.result(
                    country,
                    weight_g=1,
                    postal_code=postal_code,
                    us_tariff_rule_date="2026-07-30",
                )
                self.assertEqual(zone, first.zone)
                self.assertEqual(first_price, first.base_shipping_yen)
                if zone == "UK":
                    highest_eligible = self.result(country, weight_g=15000)
                    self.assertEqual(21154, highest_eligible.base_shipping_yen)
                    self.assertFalse(self.result(country, weight_g=15001).shippable)
                elif zone == "AU":
                    last = self.result(
                        country,
                        weight_g=22000,
                        length_cm=100,
                        width_cm=40,
                        height_cm=45,
                    )
                    self.assertEqual(22500, last.billing_weight_g)
                    self.assertEqual(last_price, last.base_shipping_yen)
                    self.assertFalse(self.result(country, weight_g=22001).shippable)
                else:
                    last = self.result(
                        country,
                        weight_g=float(rows[-1]["max_weight_g"]),
                        postal_code=postal_code,
                        us_tariff_rule_date="2026-07-30",
                    )
                    self.assertEqual(last_price, last.base_shipping_yen)


if __name__ == "__main__":
    unittest.main()
