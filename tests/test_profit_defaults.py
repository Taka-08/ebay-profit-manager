from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import streamlit_app as profit_app


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFIT_APP = PROJECT_ROOT / "streamlit_app.py"


class ProfitDefaultTest(unittest.TestCase):
    @staticmethod
    def element_with_label(elements, label: str):
        return next(element for element in elements if element.label == label)

    def test_new_ebay_calculation_uses_updated_defaults(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="ebay-defaults-test-"))
        with patch.dict(
            os.environ,
            {
                "EBAY_TOOL_WORKSPACE": str(workspace),
                "TURSO_DATABASE_URL": "",
                "TURSO_AUTH_TOKEN": "",
            },
            clear=False,
        ):
            app = AppTest.from_file(str(PROFIT_APP)).run(timeout=30)

        self.assertFalse(app.exception)
        self.assertEqual(
            0.0,
            self.element_with_label(
                app.number_input,
                "販売価格（USD / $）",
            ).value,
        )
        self.assertEqual(
            17.5,
            self.element_with_label(
                app.number_input,
                "eBay手数料率",
            ).value,
        )
        self.assertEqual(
            0.0,
            self.element_with_label(
                app.number_input,
                "広告率",
            ).value,
        )
        self.assertEqual(
            "Others",
            self.element_with_label(app.selectbox, "原産国（COO）").value,
        )

    def test_small_packet_is_excluded_without_removing_other_japan_post_services(
        self,
    ) -> None:
        inputs = profit_app.ProductInputs(
            product_name="表示対象テスト",
            sku="",
            sale_price_usd=50.0,
            buyer_shipping_usd=0.0,
            purchase_price_yen=3000.0,
            domestic_shipping_yen=20.0,
            packaging_yen=0.0,
            destination_country="アメリカ",
            weight_g=500.0,
            length_cm=0.0,
            width_cm=0.0,
            height_cm=0.0,
            ebay_fee_rate=17.5,
            overseas_fee_rate=2.0,
            ad_rate=0.0,
            other_fee_yen=0.0,
            fixed_fee_usd=0.3,
            target_profit_yen=0.0,
            product_url="",
            source_url="",
            exchange_rate=150.0,
            postal_code="10001",
        )

        results = profit_app.calculate_shipping_results(inputs)
        japan_post_services = {
            result.service
            for result in results
            if result.carrier == "日本郵便"
        }

        self.assertNotIn("小形包装物", japan_post_services)
        self.assertTrue(
            {"EMS", "国際エアパケット", "国際小包"}.issubset(
                japan_post_services
            )
        )

    def test_japan_post_zonos_uses_versioned_us_tariff_engine(self) -> None:
        inputs = profit_app.ProductInputs(
            product_name="新関税テスト",
            sku="",
            sale_price_usd=100.0,
            buyer_shipping_usd=0.0,
            purchase_price_yen=3000.0,
            domestic_shipping_yen=20.0,
            packaging_yen=0.0,
            destination_country="アメリカ",
            weight_g=500.0,
            length_cm=0.0,
            width_cm=0.0,
            height_cm=0.0,
            ebay_fee_rate=17.5,
            overseas_fee_rate=2.0,
            ad_rate=0.0,
            other_fee_yen=0.0,
            fixed_fee_usd=0.3,
            target_profit_yen=0.0,
            product_url="",
            source_url="",
            exchange_rate=100.0,
            postal_code="10001",
            country_of_origin="JP",
            mfn_rate_percent=16.5,
            us_tariff_rule_date="2026-07-29",
        )

        ems = next(
            result
            for result in profit_app.calculate_shipping_results(inputs)
            if result.carrier == "日本郵便" and result.service == "EMS"
        )
        self.assertTrue(ems.zonos_applied)
        self.assertEqual(16.5, ems.zonos_duty_rate_percent)
        self.assertEqual(1650.0, ems.zonos_duty_yen)
        self.assertEqual("JP", ems.us_tariff_country_of_origin)
        self.assertEqual(
            "speedpak-us-estimated-2026-07-29",
            ems.us_tariff_rule_version,
        )


if __name__ == "__main__":
    unittest.main()
