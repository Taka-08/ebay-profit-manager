from __future__ import annotations

import gc
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFIT_APP = PROJECT_ROOT / "streamlit_app.py"
MANAGER_APP = PROJECT_ROOT / "ebay_listing_manager" / "streamlit_app.py"


class ListingRegistrationIntegrationTest(unittest.TestCase):
    @staticmethod
    def element_with_label(elements, label: str):
        return next(element for element in elements if element.label == label)

    @staticmethod
    def button_with_key(app: AppTest, key: str):
        return next(button for button in app.button if button.key == key)

    @staticmethod
    def parse_shipping_option_label(label: str) -> tuple[str, str]:
        for carrier in ("SpeedPAK / CPaSS", "日本郵便", "FedEx", "DHL"):
            prefix = f"{carrier} / "
            if label.startswith(prefix):
                service = label[len(prefix):].split(" 送料 ", 1)[0]
                return carrier, service
        raise AssertionError(f"Unknown shipping option label: {label}")

    def configure_ebay_inputs(
        self,
        app: AppTest,
        *,
        product_name: str,
        include_size: bool = False,
        rule_date: date = date(2026, 7, 29),
    ) -> AppTest:
        self.element_with_label(app.text_input, "商品名").set_value(product_name)
        self.element_with_label(app.text_input, "郵便番号").set_value("10001")
        self.element_with_label(
            app.number_input,
            "販売価格（USD / $）",
        ).set_value(80.0)
        self.element_with_label(app.number_input, "仕入れ価格（円）").set_value(4000.0)
        self.element_with_label(app.number_input, "実重量（g）").set_value(500.0)
        self.element_with_label(app.selectbox, "原産国（COO）").set_value("JP")
        self.element_with_label(app.number_input, "MFN税率（%）").set_value(6.0)
        self.element_with_label(app.date_input, "関税ルール適用日").set_value(
            rule_date
        )
        if include_size:
            self.element_with_label(app.number_input, "長さ（cm）").set_value(20.0)
            self.element_with_label(app.number_input, "幅（cm）").set_value(15.0)
            self.element_with_label(app.number_input, "高さ（cm）").set_value(10.0)
        app.run(timeout=60)
        self.assertEqual([], list(app.exception))
        return app

    def test_cpass_registration_persists_full_fee_snapshot(self) -> None:
        profit = AppTest.from_file(str(PROFIT_APP)).run(timeout=60)
        self.assertEqual([], list(profit.exception))
        self.configure_ebay_inputs(
            profit,
            product_name="cPass送料内訳登録テスト",
            include_size=True,
            rule_date=date(2026, 8, 2),
        )
        self.element_with_label(profit.number_input, "数量").set_value(4)
        self.element_with_label(
            profit.number_input,
            "申告総価格（USD）",
        ).set_value(80.0)
        self.element_with_label(profit.text_input, "HTS / HSコード").set_value(
            "6109100012"
        )
        profit.run(timeout=60)
        self.assertEqual([], list(profit.exception))

        self.button_with_key(
            profit,
            "direct_register_SpeedPAK / CPaSS::SpeedPAK Economy",
        ).click()
        profit.run(timeout=60)
        self.assertEqual([], list(profit.exception))

        database = self.workspace / "ebay_listing_manager" / "ebay_listings.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM listings").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(1, row["cpass_applied"])
        self.assertEqual(4, row["declared_quantity"])
        self.assertEqual(80.0, row["declared_total_value_foreign"])
        self.assertEqual("6109100012", row["hts_code"])
        self.assertEqual("DDP", row["shipping_incoterm"])
        self.assertGreater(row["cpass_published_base_transport_yen"], 0)
        self.assertAlmostEqual(
            -4.7619047619,
            row["cpass_transport_adjustment_rate_percent"],
        )
        self.assertEqual(245.0, row["cpass_import_clearance_fee_yen"])
        self.assertGreater(row["cpass_estimated_duty_tax_yen"], 0)
        self.assertGreater(row["cpass_duty_processing_fee_yen"], 0)
        self.assertEqual(
            "cpass-speedpak-economy-us-2026-08-02",
            row["cpass_profile_version"],
        )
        breakdown = json.loads(row["shipping_breakdown_json"])
        self.assertTrue(breakdown["cpass_applied"])
        self.assertEqual(
            row["cpass_published_base_transport_yen"],
            breakdown["cpass_published_base_transport_yen"],
        )
        self.assertEqual(row["planned_shipping_yen"], breakdown["total_yen"])

    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="ebay-registration-test-"))
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

    def test_profit_button_saves_and_manager_reads_same_row(self) -> None:
        profit = AppTest.from_file(str(PROFIT_APP)).run(timeout=60)
        self.assertEqual([], list(profit.exception))

        self.configure_ebay_inputs(
            profit,
            product_name="登録連携テスト商品",
        )

        registration_radio = self.element_with_label(
            profit.radio,
            "登録する配送方法",
        )
        self.assertGreaterEqual(len(registration_radio.options), 2)
        selected_option_label = registration_radio.options[1]
        selected_carrier, selected_service = self.parse_shipping_option_label(
            selected_option_label
        )
        selected_result_id = f"{selected_carrier}::{selected_service}"
        registration_radio.set_value(selected_result_id)
        profit.run(timeout=60)
        self.assertEqual([], list(profit.exception))

        self.element_with_label(profit.button, "出品管理へ登録").click()
        profit.run(timeout=60)
        self.assertEqual([], list(profit.exception))
        self.assertTrue(
            any("保存ID" in message.value for message in profit.success),
            "Registration success did not include the saved ID.",
        )

        database = self.workspace / "ebay_listing_manager" / "ebay_listings.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            row = connection.execute(
                """
                SELECT id, product_name, expected_shipping_carrier,
                       expected_shipping_service, planned_shipping_yen,
                       expected_profit_yen, planned_profit_margin,
                       country_of_origin, mfn_rate_percent,
                       us_tariff_applied_rate_percent,
                       us_tariff_rule_version
                FROM listings
                """
            ).fetchone()
            count = connection.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        self.assertEqual(1, count)
        self.assertEqual("登録連携テスト商品", row[1])
        self.assertEqual(selected_carrier, row[2])
        self.assertEqual(selected_service, row[3])
        self.assertGreater(row[4], 0)
        self.assertIsNotNone(row[5])
        self.assertIsNotNone(row[6])
        self.assertEqual("JP", row[7])
        self.assertEqual(6.0, row[8])
        self.assertEqual(12.5, row[9])
        self.assertEqual("speedpak-us-estimated-2026-07-29", row[10])

        event_path = self.workspace / "ebay_listing_manager" / "registration_event.json"
        log_path = self.workspace / "ebay_listing_manager" / "logs" / "registration.log"
        self.assertTrue(event_path.exists())
        self.assertTrue(log_path.exists())
        event = json.loads(event_path.read_text(encoding="utf-8"))
        self.assertEqual(row[0], event["listing_id"])
        self.assertEqual(1, event["total_count"])

        manager = AppTest.from_file(str(MANAGER_APP)).run(timeout=60)
        self.assertEqual([], list(manager.exception))
        self.assertTrue(any("出品管理" in title.value for title in manager.title))
        mobile_markup = "\n".join(item.value for item in manager.markdown)
        self.assertIn("mobile-listing-card", mobile_markup)
        self.assertIn("販売価格（USD）", mobile_markup)
        self.assertIn("仕入れ価格", mobile_markup)
        self.assertIn(">詳細</summary>", mobile_markup)
        self.assertIn(">編集</a>", mobile_markup)
        self.assertIn(">削除</a>", mobile_markup)

        first_event_id = event["event_id"]
        self.element_with_label(profit.button, "出品管理へ登録").click()
        profit.run(timeout=60)
        self.assertEqual([], list(profit.exception))
        duplicate_event = json.loads(event_path.read_text(encoding="utf-8"))
        self.assertEqual(first_event_id, duplicate_event["event_id"])
        self.assertTrue(
            any("二重登録を防止" in message.value for message in profit.warning)
        )
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(
                1,
                connection.execute("SELECT COUNT(*) FROM listings").fetchone()[0],
            )

        registration_radio = self.element_with_label(
            profit.radio,
            "登録する配送方法",
        )
        different_option_label = next(
            option
            for option in registration_radio.options
            if option != selected_option_label
        )
        different_carrier, different_service = self.parse_shipping_option_label(
            different_option_label
        )
        registration_radio.set_value(
            f"{different_carrier}::{different_service}"
        )
        profit.run(timeout=60)
        self.element_with_label(profit.button, "出品管理へ登録").click()
        profit.run(timeout=60)
        self.assertEqual([], list(profit.exception))
        second_event = json.loads(event_path.read_text(encoding="utf-8"))
        self.assertNotEqual(first_event_id, second_event["event_id"])

        manager.run(timeout=60)
        self.assertEqual([], list(manager.exception))
        self.assertEqual(
            second_event["event_id"],
            manager.session_state["last_registration_event_id"],
        )
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(
                2,
                connection.execute("SELECT COUNT(*) FROM listings").fetchone()[0],
            )

        manager.query_params["mobile_delete_listing_id"] = str(
            second_event["listing_id"]
        )
        manager.query_params["mobile_delete_section"] = "active"
        manager.query_params["mobile_delete_click"] = "integration-test"
        manager.run(timeout=60)
        self.assertEqual([], list(manager.exception))
        self.element_with_label(manager.button, "削除を確定").click()
        manager.run(timeout=60)
        self.assertEqual([], list(manager.exception))
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(
                1,
                connection.execute("SELECT COUNT(*) FROM listings").fetchone()[0],
            )

        del profit
        del manager

    def test_detail_registration_uses_shared_payload_for_all_carriers(self) -> None:
        profit = AppTest.from_file(str(PROFIT_APP)).run(timeout=60)
        self.assertEqual([], list(profit.exception))
        self.configure_ebay_inputs(
            profit,
            product_name="詳細登録共通処理テスト",
            include_size=True,
        )
        self.element_with_label(profit.text_area, "メモ").set_value(
            "詳細画面から共通保存"
        )
        profit.run(timeout=60)
        self.assertEqual([], list(profit.exception))

        direct_buttons = [
            button
            for button in profit.button
            if button.label == "この配送方法で出品管理ツールへ登録"
        ]
        self.assertGreaterEqual(len(direct_buttons), 4)
        visible_carriers = {
            button.key.removeprefix("direct_register_").split("::", 1)[0]
            for button in direct_buttons
        }
        self.assertTrue(
            {"日本郵便", "SpeedPAK / CPaSS", "FedEx", "DHL"}.issubset(
                visible_carriers
            )
        )

        targets = (
            ("日本郵便", "EMS"),
            ("SpeedPAK / CPaSS", "SpeedPAK Economy"),
            ("FedEx", "International Connect Plus (FICP)"),
            ("DHL", "Express Worldwide"),
        )
        database = self.workspace / "ebay_listing_manager" / "ebay_listings.sqlite3"

        for expected_count, (carrier, service) in enumerate(targets, start=1):
            with self.subTest(carrier=carrier, service=service):
                key = f"direct_register_{carrier}::{service}"
                direct_button = self.button_with_key(profit, key)
                self.assertFalse(direct_button.disabled)
                direct_button.click()
                profit.run(timeout=60)
                self.assertEqual([], list(profit.exception))
                self.assertTrue(
                    any(
                        carrier in message.value
                        and service in message.value
                        and "出品管理ツールへ登録しました" in message.value
                        for message in profit.success
                    )
                )

                with closing(sqlite3.connect(database)) as connection:
                    connection.row_factory = sqlite3.Row
                    row = connection.execute(
                        """
                        SELECT *
                        FROM listings
                        ORDER BY id DESC
                        LIMIT 1
                        """
                    ).fetchone()
                    count = connection.execute(
                        "SELECT COUNT(*) FROM listings"
                    ).fetchone()[0]
                self.assertEqual(expected_count, count)
                self.assertEqual("eBay", row["platform"])
                self.assertEqual("詳細登録共通処理テスト", row["product_name"])
                self.assertEqual(carrier, row["expected_shipping_carrier"])
                self.assertEqual(service, row["expected_shipping_service"])
                self.assertEqual(500.0, row["package_weight_g"])
                self.assertEqual(20.0, row["package_length_cm"])
                self.assertEqual(15.0, row["package_width_cm"])
                self.assertEqual(10.0, row["package_height_cm"])
                self.assertGreater(row["planned_shipping_yen"], 0)
                self.assertIsNotNone(row["expected_profit_yen"])
                self.assertIsNotNone(row["planned_profit_margin"])
                self.assertEqual(
                    "詳細画面から共通保存",
                    row["platform_memo"],
                )
                self.assertEqual("JP", row["country_of_origin"])
                self.assertEqual(6.0, row["mfn_rate_percent"])
                self.assertEqual(12.5, row["us_tariff_applied_rate_percent"])
                self.assertEqual(
                    "speedpak-us-estimated-2026-07-29",
                    row["us_tariff_rule_version"],
                )

                breakdown = json.loads(row["shipping_breakdown_json"])
                self.assertEqual(carrier, breakdown["carrier"])
                self.assertEqual(service, breakdown["service"])
                self.assertEqual(
                    round(row["planned_shipping_yen"]),
                    breakdown["total_yen"],
                )
                self.assertEqual(
                    round(row["planned_fuel_surcharge_yen"]),
                    breakdown["fuel_surcharge_yen"],
                )
                self.assertEqual(
                    round(row["planned_additional_fee_yen"]),
                    breakdown["additional_total_yen"],
                )
                if service == "SpeedPAK Economy":
                    self.assertEqual(
                        "orange-connex-economy-japan-2026-07-30",
                        breakdown["rate_book_version"],
                    )
                    self.assertEqual("2026-07-30", breakdown["effective_from"])
                    self.assertEqual([5], breakdown["source_pages"])

                if expected_count == 1:
                    self.button_with_key(profit, key).click()
                    profit.run(timeout=60)
                    self.assertEqual([], list(profit.exception))
                    with closing(sqlite3.connect(database)) as connection:
                        self.assertEqual(
                            1,
                            connection.execute(
                                "SELECT COUNT(*) FROM listings"
                            ).fetchone()[0],
                        )
                    self.assertTrue(
                        any(
                            "二重登録を防止" in message.value
                            for message in profit.warning
                        )
                    )

        del profit

    def test_eu_economy_registration_persists_rate_snapshot(self) -> None:
        profit = AppTest.from_file(str(PROFIT_APP)).run(timeout=60)
        self.assertEqual([], list(profit.exception))
        self.configure_ebay_inputs(
            profit,
            product_name="EU料金スナップショットテスト",
            include_size=True,
        )
        self.element_with_label(profit.selectbox, "配送先の国").set_value("FR")
        profit.run(timeout=60)
        self.assertEqual([], list(profit.exception))

        key = "direct_register_SpeedPAK / CPaSS::SpeedPAK Economy"
        self.button_with_key(profit, key).click()
        profit.run(timeout=60)
        self.assertEqual([], list(profit.exception))

        database = self.workspace / "ebay_listing_manager" / "ebay_listings.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM listings ORDER BY id DESC LIMIT 1"
            ).fetchone()

        self.assertEqual("FR", row["destination_country"])
        self.assertEqual("SpeedPAK Economy", row["expected_shipping_service"])
        self.assertEqual(3356.0, row["planned_base_shipping_yen"])
        breakdown = json.loads(row["shipping_breakdown_json"])
        self.assertEqual("FR", breakdown["destination_country"])
        self.assertEqual(
            "orange-connex-economy-japan-2026-07-30",
            breakdown["rate_book_version"],
        )
        self.assertEqual("2026-07-30", breakdown["effective_from"])
        self.assertEqual([12], breakdown["source_pages"])

        del profit


if __name__ == "__main__":
    unittest.main()
