"""Disposable Stage-5 UI fixture; all DB access confined to .tmp_stage5/preview."""
import json
import os
from pathlib import Path
import runpy
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
run = os.environ.get('STAGE5_PREVIEW_RUN', 'default')
if not re.fullmatch(r'[A-Za-z0-9_-]+', run):
    raise RuntimeError('Invalid local preview run name')
WORKSPACE = ROOT / '.tmp_stage5' / 'preview' / run
WORKSPACE.mkdir(parents=True, exist_ok=True)
os.environ.update(EBAY_TOOL_WORKSPACE=str(WORKSPACE), EBAY_LISTING_DB_PATH='', TURSO_DATABASE_URL='', TURSO_AUTH_TOKEN='')
import app_database
from app_paths import resolve_listing_db_path
from integrated_ebay.migrations import run_schema_migrations
from integrated_ebay.services import ProductCatalogService
from integrated_ebay.draft_service import ListingDraftService


def local_connection(path):
    path = Path(path).resolve()
    if not path.is_relative_to(WORKSPACE.resolve()):
        raise RuntimeError('Refused a database outside the disposable fixture')
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, factory=app_database.ClosingSQLiteConnection)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c


app_database.get_database_connection = local_connection
app_database._secret_value = lambda *args, **kwargs: ''
APP = ROOT / 'ebay_listing_manager' / 'streamlit_app.py'
factory = lambda: local_connection(resolve_listing_db_path(APP))
db = resolve_listing_db_path(APP)
backup = WORKSPACE / 'before_stage5.sqlite3'
if db.exists() and not backup.exists():
    with local_connection(db) as c, local_connection(backup) as target:
        c.backup(target)
run_schema_migrations(factory)
catalog = ProductCatalogService(factory)
drafts = ListingDraftService(factory)
if not catalog.list_products(status='ALL'):
    for engine in ('chromium', 'webkit'):
        for width in (1440, 390, 414, 360):
            name = f'E2E-{engine}-{width}'
            pid = catalog.create_product(dict(product_name=name, sku=name, category='Cameras', country_of_origin='JP',
                weight_g=500, length_cm=20, width_cm=10, height_cm=5, purchase_price=1000))
            catalog.update_inventory(pid, dict(stock_mode='IN_STOCK', on_hand_quantity=2, reserved_quantity=0))
            did = drafts.create(pid, actor_id='Fixture', price=30)
            drafts.generate(did, expected_revision=1, actor_id='Fixture')
            drafts.update(did, dict(category_name='Cameras', category_id='31388', condition_name='Used', condition_id='3000',
                publication_input_json=json.dumps(dict(exchange_rate=150, shipping_yen=500, shipping_carrier='Japan Post',
                    shipping_service='EMS', specifics_reviewed=True))), expected_revision=2, actor_id='Fixture')
runpy.run_path(str(APP), run_name='__main__')
