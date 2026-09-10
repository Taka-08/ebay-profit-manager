from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import app_database
from app_paths import resolve_listing_db_path
from integrated_ebay.draft_service import ListingDraftService
from integrated_ebay.migrations import run_schema_migrations
from integrated_ebay.services import ProductCatalogService


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "ebay_listing_manager" / "streamlit_app.py"


class ListingDraftUiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="draft-ui-")
        self.env = patch.dict(os.environ, {"EBAY_TOOL_WORKSPACE": self.temp.name, "EBAY_LISTING_DB_PATH": "",
                                          "TURSO_DATABASE_URL": "", "TURSO_AUTH_TOKEN": ""})
        self.env.start()
        self.secrets = patch.object(app_database, "_secret_value", return_value="")
        self.secrets.start()
        self.factory = lambda: app_database.get_database_connection(resolve_listing_db_path(APP))
        run_schema_migrations(self.factory)
        catalog = ProductCatalogService(self.factory)
        self.product_id = catalog.create_product({"product_name": "Camera", "platform": "eBay", "brand": "Example", "category": "Cameras"})
        catalog.update_inventory(self.product_id, {"stock_mode": "IN_STOCK", "on_hand_quantity": 3, "reserved_quantity": 0})
        self.service = ListingDraftService(self.factory)

    def tearDown(self):
        self.secrets.stop()
        self.env.stop()
        self.temp.cleanup()

    @staticmethod
    def button(app, label):
        return next(widget for widget in app.button if widget.label == label)

    def app(self):
        app = AppTest.from_file(str(APP)).run(timeout=60)
        self.assertEqual([], list(app.exception))
        return app

    def test_product_navigation_and_generate_retain_product_id(self):
        app = self.app()
        self.button(app, "AI出品下書きを作成").click().run(timeout=60)
        self.assertEqual([], list(app.exception))
        self.assertEqual("AI出品", app.session_state["manager_main_tab"])
        self.assertEqual(self.product_id, app.session_state["ai_product_id"])
        app.text_input(key="ai_draft_actor").set_value("Tester")
        self.button(app, "AI下書きを生成").click().run(timeout=60)
        self.assertEqual([], list(app.exception))
        drafts = self.service.list(self.product_id)
        self.assertEqual(1, len(drafts))
        self.assertEqual("READY_FOR_REVIEW", drafts[0]["status"])
        self.assertTrue(any(w.label == "Title" for w in app.text_input))
        app.run(timeout=60)
        self.assertEqual(1, len(self.service.list(self.product_id)))

    def test_edit_save_approve_and_archive(self):
        draft_id = self.service.create(self.product_id, actor_id="Setup")
        self.service.generate(draft_id, actor_id="Setup", expected_revision=1)
        app = self.app()
        app.text_input(key="ai_draft_actor").set_value("Reviewer")
        next(w for w in app.text_input if w.label.startswith("Condition（")).set_value("Used")
        next(w for w in app.number_input if w.label == "Price").set_value(25.0)
        self.button(app, "下書きを保存").click().run(timeout=60)
        self.assertEqual([], list(app.exception))
        self.assertEqual(25, self.service.get(draft_id)["price"])
        self.button(app, "レビュー待ちにする").click().run(timeout=60)
        next(w for w in app.checkbox if w.label.startswith("保存済みの本文")).check().run(timeout=60)
        self.button(app, "承認").click().run(timeout=60)
        self.assertEqual([], list(app.exception))
        self.assertEqual("APPROVED", self.service.get(draft_id)["status"])
        self.button(app, "アーカイブ").click().run(timeout=60)
        self.assertEqual([], list(app.exception))
        self.assertEqual("ARCHIVED", self.service.get(draft_id)["status"])
        self.assertTrue(self.button(app, "下書きを保存").disabled)

    def test_missing_actor_and_provider_error_visible(self):
        app = self.app()
        self.button(app, "AI下書きを生成").click().run(timeout=60)
        self.assertEqual([], list(app.exception))
        self.assertTrue(any("操作者名" in w.value for w in app.error))
        self.assertEqual([], self.service.list())
        app.text_input(key="ai_draft_actor").set_value("Tester")
        with patch("integrated_ebay.ai_listing.LocalDeterministicProvider.generate", side_effect=TimeoutError("secret-do-not-show")):
            self.button(app, "AI下書きを生成").click().run(timeout=60)
        self.assertEqual([], list(app.exception))
        self.assertTrue(any("既存内容は保持" in w.value for w in app.error))
        self.assertFalse(any("secret-do-not-show" in w.value for w in app.error))
        self.assertEqual("DRAFT", self.service.list()[0]["status"])

    def test_existing_tabs_and_mobile_styles_available(self):
        app = self.app()
        self.assertTrue({"出品管理", "商品マスター", "AI出品", "分析・集計", "予定と実績の差額分析"} <= {t.label for t in app.tabs})
        styles = "\n".join(w.value for w in app.markdown)
        self.assertIn("@media(max-width:768px)", styles)
        self.assertIn("min-height:46px", styles)

    def test_saved_gbp_calculation_preview_matches_registration(self):
        app = self.app()
        with self.factory() as c:
            c.execute("INSERT INTO listings (product_name, product_id, platform, listing_price_usd, currency_code, listing_date, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                      ("GBP source", self.product_id, "eBay", 25.0, "GBP", "2026-09-10", "出品中", "2026-09-10", "2026-09-10"))
        app.run(timeout=60)
        source = app.selectbox(key=f"ai_source_{self.product_id}")
        source.select(1).run(timeout=60)
        self.assertEqual([], list(app.exception))
        self.assertEqual("GBP", next(w for w in app.selectbox if w.label == "販売通貨").value)
        self.assertEqual(25.0, next(w for w in app.number_input if w.label == "販売価格（空欄可）").value)

    def test_malformed_image_url_does_not_break_preview(self):
        ProductCatalogService(self.factory).add_image(self.product_id, {"url": "https://[invalid", "file_name": "Invalid URL"})
        app = self.app()
        app.checkbox(key=f"ai_images_{self.product_id}").check().run(timeout=60)
        self.assertEqual([], list(app.exception))
        self.assertTrue(any("プレビューできるHTTPS URL" in w.value for w in app.caption))


if __name__ == "__main__":
    unittest.main()
