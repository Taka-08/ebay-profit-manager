from __future__ import annotations

import gc
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
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

    def configure_ebay_inputs(
        self,
        app: AppTest,
        *,
        product_name: str,
        include_size: bool = False,
    ) -> AppTest:
        self.element_with_label(app.text_input, "商品名").set_value(product_name)
        self.element_with_label(app.text_input, "郵便番号").set_value("10001")
        self.element_with_label(
            app.number_input,
            "販売価格（USD / $）",
        ).set_value(80.0)
        self.element_with_label(app.number_input, "仕入れ価格（円）").set_value(4000.0)
        self.element_with_label(app.number_input, "実重量（g）").set_value(500.0)
        if include_size:
            self.element_with_label(app.number_input, "長さ（cm）").set_value(20.0)
            self.element_with_label(app.number_input, "幅（cm）").set_value(15.0)
            self.element_with_label(app.number_input, "高さ（cm）").set_value(10.0)
        app.run(timeout=60)
        self.assertEqual([], list(app.exception))
        return app

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
        carrier_and_service = selected_option_label.split(" 送料 ", 1)[0]
        selected_carrier, selected_service = carrier_and_service.split(" / ", 1)
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
                       expected_profit_yen, planned_profit_margin
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
        carrier_and_service = different_option_label.split(" 送料 ", 1)[0]
        different_carrier, different_service = carrier_and_service.split(" / ", 1)
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
            ("日本郵便", "小形包装物"),
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


if __name__ == "__main__":
    unittest.main()
