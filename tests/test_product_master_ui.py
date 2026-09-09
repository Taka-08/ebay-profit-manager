from __future__ import annotations

import gc
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app_database import get_database_connection
from app_paths import resolve_listing_db_path
from integrated_ebay.migrations import run_schema_migrations
from integrated_ebay.services import ProductCatalogService


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFIT_APP = PROJECT_ROOT / "streamlit_app.py"
MANAGER_APP = PROJECT_ROOT / "ebay_listing_manager" / "streamlit_app.py"


class ProductMasterUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="ebay-product-ui-test-"))
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

    def connection_factory(self):
        return get_database_connection(resolve_listing_db_path(MANAGER_APP))

    def create_product(self) -> str:
        run_schema_migrations(self.connection_factory)
        return ProductCatalogService(self.connection_factory).create_product({
            "product_name": "Product master UI test",
            "platform": "eBay",
            "sku": "UI-001",
            "brand": "Example",
            "country_of_origin": "JP",
            "hts_code": "9006000000",
            "weight_g": 750,
            "length_cm": 20,
            "width_cm": 15,
            "height_cm": 10,
            "purchase_price": 12000,
            "purchase_currency": "JPY",
            "status": "ACTIVE",
        })

    def test_manager_renders_product_master_without_breaking_existing_tabs(self) -> None:
        self.create_product()
        app = AppTest.from_file(str(MANAGER_APP)).run(timeout=60)
        self.assertEqual([], list(app.exception))
        tab_labels = [tab.label for tab in app.tabs]
        self.assertIn("出品管理", tab_labels)
        self.assertIn("商品マスター", tab_labels)
        self.assertIn("分析・集計", tab_labels)
        self.assertTrue(any(header.value == "商品マスター" for header in app.header))
        self.assertTrue(
            any(value.value == "Product master UI test" for value in app.text_input)
        )

    def test_product_query_prefills_profit_calculator(self) -> None:
        product_id = self.create_product()
        app = AppTest.from_file(str(PROFIT_APP))
        app.query_params["product_id"] = product_id
        app.run(timeout=60)
        self.assertEqual([], list(app.exception))
        self.assertEqual(product_id, app.session_state["selected_product_master_id"])
        self.assertEqual("Product master UI test", app.session_state["input_product_name"])
        self.assertEqual("UI-001", app.session_state["input_sku"])
        self.assertEqual(12000.0, app.session_state["input_purchase_price_yen"])
        self.assertEqual(750.0, app.session_state["input_weight_g"])
        self.assertEqual("JP", app.session_state["input_country_of_origin"])
        self.assertEqual("9006000000", app.session_state["input_hts_code"])


if __name__ == "__main__":
    unittest.main()
