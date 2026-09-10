"""Disposable local preview of the real manager. Never uses Turso/Secrets.

Run with Streamlit on 127.0.0.1. Data stays in ignored .tmp_stage4/preview.
"""

import os
from pathlib import Path
import runpy
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
WORKSPACE = ROOT / ".tmp_stage4" / "preview"
WORKSPACE.mkdir(parents=True, exist_ok=True)
os.environ["EBAY_TOOL_WORKSPACE"] = str(WORKSPACE)
os.environ["EBAY_LISTING_DB_PATH"] = ""
os.environ["TURSO_DATABASE_URL"] = ""
os.environ["TURSO_AUTH_TOKEN"] = ""

import app_database
from app_paths import resolve_listing_db_path
from integrated_ebay.draft_service import ListingDraftService
from integrated_ebay.migrations import run_schema_migrations
from integrated_ebay.services import ProductCatalogService


def local_only_connection(path):
    path = Path(path).resolve()
    if not path.is_relative_to(WORKSPACE.resolve()):
        raise RuntimeError("Preview refused a database outside its disposable workspace")
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, factory=app_database.ClosingSQLiteConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


app_database.get_database_connection = local_only_connection
app_database._secret_value = lambda *args, **kwargs: ""
APP = ROOT / "ebay_listing_manager" / "streamlit_app.py"
factory = lambda: local_only_connection(resolve_listing_db_path(APP))
run_schema_migrations(factory)
catalog = ProductCatalogService(factory)
if not catalog.list_products(status="ALL"):
    product_id = catalog.create_product({
        "product_name": "Example Digital Camera EX-1", "platform": "eBay", "sku": "DEMO-STAGE4",
        "brand": "Example", "model_number": "EX-1", "category": "Cameras", "country_of_origin": "JP",
    })
    catalog.update_inventory(product_id, {"stock_mode": "IN_STOCK", "on_hand_quantity": 5, "reserved_quantity": 1})
    drafts = ListingDraftService(factory)
    draft_id = drafts.create(product_id, actor_id="Preview setup", price=39.99)
    drafts.generate(draft_id, actor_id="Preview setup", expected_revision=1)

runpy.run_path(str(APP), run_name="__main__")
