from __future__ import annotations

import json
import unittest
from pathlib import Path

import cpass_speedpak
import streamlit_app as app


ROOT = Path(__file__).resolve().parents[1]


def make_inputs(
    *,
    weight_g: float,
    length_cm: float,
    width_cm: float,
    height_cm: float,
    declared_total: float,
    origin: str,
    hts_code: str,
) -> app.ProductInputs:
    return app.ProductInputs(
        product_name="cPass benchmark",
        sku="",
        sale_price_usd=declared_total,
        buyer_shipping_usd=0,
        purchase_price_yen=0,
        domestic_shipping_yen=0,
        packaging_yen=0,
        destination_country="US",
        weight_g=weight_g,
        length_cm=length_cm,
        width_cm=width_cm,
        height_cm=height_cm,
        ebay_fee_rate=0,
        overseas_fee_rate=0,
        ad_rate=0,
        other_fee_yen=0,
        fixed_fee_usd=0,
        target_profit_yen=0,
        product_url="",
        source_url="",
        exchange_rate=157.6,
        postal_code="02150-2769",
        currency_code="USD",
        usd_jpy_rate=157.6,
        country_of_origin=origin,
        mfn_rate_percent=0,
        us_tariff_rule_date="2026-08-02",
        declared_quantity=4,
        declared_total_value_foreign=declared_total,
        hts_code=hts_code,
        shipping_incoterm="DDP",
    )


def speedpak_result(inputs: app.ProductInputs) -> app.ShippingResult:
    return next(
        result
        for result in app.calculate_shipping_results(inputs)
        if result.carrier == "SpeedPAK / CPaSS"
        and result.service == "SpeedPAK Economy"
    )


class CPassSpeedPAKEconomyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cpass_speedpak.load_cpass_config.cache_clear()

    def test_supplied_orange_economy_rate_cells_and_chelsea_zone(self) -> None:
        rate_book = json.loads((ROOT / "shipping_rates.json").read_text(encoding="utf-8"))
        economy = next(
            service
            for service in rate_book["services"]
            if service["carrier"] == "SpeedPAK / CPaSS"
            and service["service"] == "SpeedPAK Economy"
        )
        zone, reason = app.resolve_service_zone(economy, "US", "02150-2769")
        self.assertIsNone(reason)
        self.assertEqual("US_MAINLAND", zone)
        expected = {500: 2040, 800: 2676, 1000: 2990, 1300: 3333, 2000: 5194}
        for weight_g, amount_yen in expected.items():
            with self.subTest(weight_g=weight_g):
                row = app.find_rate_row(economy, "US", "US_MAINLAND", weight_g)
                self.assertIsNotNone(row)
                self.assertEqual(amount_yen, row["base_shipping_yen"])

    def test_observed_five_fee_components_reproduce_all_four_totals(self) -> None:
        profile = cpass_speedpak.active_cpass_profile("US", "2026-08-02")
        self.assertIsNotNone(profile)
        cases = (
            (2676, 2549, 40.00, "VN", "6109100012", 306, 788, 17, 3905),
            (5194, 4947, 120.00, "VN", "6109100012", 594, 2364, 50, 8200),
            (2990, 2848, 86.37, "VN", "6109100012", 342, 1701, 36, 5172),
            (3333, 3174, 57.20, "JP", "4202923131", 381, 1127, 24, 4951),
        )
        for published, base, declared, origin, hts, fuel, duty, processing, total in cases:
            with self.subTest(total=total):
                result = cpass_speedpak.calculate_cpass_shipping_breakdown(
                    profile=profile,
                    published_base_transport_yen=published,
                    declared_value_foreign=declared,
                    declared_currency="USD",
                    exchange_rate=157.6,
                    quantity=4,
                    country_of_origin=origin,
                    mfn_rate_percent=0,
                    rule_date="2026-08-02",
                    hts_code=hts,
                    incoterm="DDP",
                )
                self.assertEqual(245, result.import_clearance_fee_yen)
                self.assertEqual(published, result.published_base_transport_yen)
                self.assertEqual(base, result.base_transport_yen)
                self.assertEqual(fuel, result.fuel_surcharge_yen)
                self.assertEqual(duty, result.estimated_duty_tax_yen)
                self.assertEqual(processing, result.duty_processing_fee_yen)
                self.assertEqual(total, result.total_shipping_yen)

    def test_integrated_cpass_benchmarks_match_all_four_samples(self) -> None:
        cases = (
            (750, 31.4, 17.5, 11.0, 40.00, "VN", "6109100012", 755.5625, 756, 2549, 3905),
            (2000, 31.4, 17.5, 11.0, 120.00, "VN", "6109100012", 755.5625, 2000, 4947, 8200),
            (1000, 31.4, 17.5, 11.0, 86.37, "VN", "6109100012", 755.5625, 1000, 2848, 5172),
            (350, 50.0, 17.5, 11.0, 57.20, "JP", "4202923131", 1203.125, 1204, 3174, 4951),
        )
        for (
            weight,
            length,
            width,
            height,
            declared,
            origin,
            hts,
            volumetric,
            billing,
            base,
            observed,
        ) in cases:
            with self.subTest(observed=observed):
                result = speedpak_result(
                    make_inputs(
                        weight_g=weight,
                        length_cm=length,
                        width_cm=width,
                        height_cm=height,
                        declared_total=declared,
                        origin=origin,
                        hts_code=hts,
                    )
                )
                self.assertTrue(result.cpass_applied)
                self.assertEqual("US_MAINLAND", result.zone)
                self.assertAlmostEqual(volumetric, result.volumetric_weight_g or 0)
                self.assertEqual(billing, result.billing_weight_g)
                self.assertEqual(base, result.base_shipping_yen)
                self.assertEqual(observed, result.total_shipping_yen)
                self.assertEqual(hts, result.cpass_hts_code)

    def test_non_us_speedpak_keeps_orange_connex_profile(self) -> None:
        inputs = make_inputs(
            weight_g=1000,
            length_cm=40,
            width_cm=20,
            height_cm=10,
            declared_total=50,
            origin="JP",
            hts_code="",
        )
        inputs = app.ProductInputs(**{**inputs.__dict__, "destination_country": "FR", "postal_code": ""})
        result = speedpak_result(inputs)
        self.assertFalse(result.cpass_applied)
        self.assertEqual(1000, result.volumetric_weight_g)
        self.assertEqual("orange-connex-economy-japan-2026-07-30", result.rate_book_version)

    def test_registration_breakdown_contains_cpass_snapshot(self) -> None:
        result = speedpak_result(
            make_inputs(
                weight_g=1000,
                length_cm=31.4,
                width_cm=17.5,
                height_cm=11,
                declared_total=86.37,
                origin="VN",
                hts_code="6109100012",
            )
        )
        payload = app.shipping_breakdown_payload(result, "2026-08-02T00:00:00+09:00")
        self.assertEqual(result.total_shipping_yen, payload["total_yen"])
        self.assertEqual(2990, payload["cpass_published_base_transport_yen"])
        self.assertAlmostEqual(
            -4.7619047619,
            payload["cpass_transport_adjustment_rate_percent"],
        )
        self.assertEqual(245, payload["cpass_import_clearance_fee_yen"])
        self.assertEqual(1701, payload["cpass_estimated_duty_tax_yen"])
        self.assertEqual(36, payload["cpass_duty_processing_fee_yen"])
        self.assertEqual("6109100012", payload["cpass_hts_code"])
        self.assertEqual(
            payload["total_yen"],
            sum(item["amount_yen"] for item in payload["items"]),
        )


if __name__ == "__main__":
    unittest.main()
