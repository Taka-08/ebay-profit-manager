from __future__ import annotations

import unittest
from datetime import date

from us_tariff import (
    calculate_us_duty_amount,
    calculate_us_tariff_rate,
    load_us_tariff_config,
    supported_origins,
)


class USTariffEngineTest(unittest.TestCase):
    def test_origin_master_contains_every_required_origin(self) -> None:
        self.assertEqual(
            {
                "JP",
                "EU",
                "MY",
                "TW",
                "VN",
                "KR",
                "CH",
                "GB",
                "TH",
                "US",
                "CN",
                "HK",
                "Others",
            },
            set(supported_origins()),
        )
        rule = load_us_tariff_config()["rules"][0]
        self.assertEqual("2026-07-29", rule["effective_from"])
        self.assertEqual(
            {
                "JP": 12.5,
                "EU": 10.0,
                "MY": 10.0,
                "TW": 10.0,
                "VN": 12.5,
                "KR": 12.5,
                "CH": 12.5,
                "GB": 10.0,
                "TH": 12.5,
                "US": 0.0,
                "CN": 30.0,
                "HK": 15.0,
                "Others": 10.0,
            },
            rule["origin_rates_percent"],
        )
        self.assertEqual([], rule["additional_duties"])
        self.assertEqual([], rule["exemptions"])
        self.assertEqual([], rule["special_tariffs"])

    def test_japan_uses_greater_of_mfn_and_12_5_percent(self) -> None:
        expected = {
            0.0: 12.5,
            6.0: 12.5,
            9.0: 12.5,
            12.5: 12.5,
            16.5: 16.5,
            32.0: 32.0,
        }
        for mfn, final_rate in expected.items():
            with self.subTest(mfn=mfn):
                result = calculate_us_tariff_rate("JP", mfn, date(2026, 7, 29))
                self.assertEqual(final_rate, result.applied_rate_percent)
                self.assertFalse(result.legacy_compatibility)

    def test_other_origin_estimated_ratios(self) -> None:
        expected = {"CN": 30.0, "HK": 15.0, "US": 0.0, "GB": 10.0, "VN": 12.5}
        for origin, final_rate in expected.items():
            with self.subTest(origin=origin):
                result = calculate_us_tariff_rate(origin, 99.0, "2026-07-29")
                self.assertEqual(final_rate, result.applied_rate_percent)

    def test_product_price_only_is_taxable_and_rounds_half_up(self) -> None:
        result = calculate_us_duty_amount(
            "JP",
            6.0,
            product_price=100.0,
            exchange_rate=100.0,
            rule_date="2026-07-29",
        )
        self.assertEqual(10000.0, result.taxable_base_yen)
        self.assertEqual(1250.0, result.duty_amount_yen)

        half_yen = calculate_us_duty_amount(
            "JP",
            17.5,
            product_price=35.0,
            exchange_rate=100.0,
            rule_date="2026-07-29",
        )
        self.assertEqual(612.5, half_yen.unrounded_duty_amount_yen)
        self.assertEqual(613.0, half_yen.duty_amount_yen)

    def test_missing_origin_and_pre_effective_date_use_legacy_rule(self) -> None:
        missing = calculate_us_tariff_rate("", 0.0, "2026-08-01")
        historical = calculate_us_tariff_rate("JP", 0.0, "2026-07-28")
        self.assertTrue(missing.legacy_compatibility)
        self.assertTrue(historical.legacy_compatibility)
        self.assertEqual(10.0, missing.applied_rate_percent)
        self.assertEqual(10.0, historical.applied_rate_percent)


if __name__ == "__main__":
    unittest.main()
