"""New disposable local UI server. Never opens the user's DB or Secrets."""
import json
import os
from pathlib import Path
import re
import runpy
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
run = os.environ.get('STAGE6_PREVIEW_RUN', '')
if not re.fullmatch(r'[A-Za-z0-9_-]+', run):
    raise RuntimeError('Set a new STAGE6_PREVIEW_RUN for an isolated preview')
WORKSPACE = ROOT / '.tmp_stage6' / 'preview' / run
WORKSPACE.mkdir(parents=True, exist_ok=True)
os.environ.update(EBAY_TOOL_WORKSPACE=str(WORKSPACE), EBAY_LISTING_DB_PATH='',
                  TURSO_DATABASE_URL='', TURSO_AUTH_TOKEN='', EBAY_EXECUTION_MODE='mock')
import app_database
from app_paths import resolve_listing_db_path
from integrated_ebay.approval_migration import initialize_approval_storage
from integrated_ebay.approval_service import ApprovalService
from integrated_ebay.services import ProductCatalogService
from integrated_ebay.draft_service import ListingDraftService


def local_connection(path):
    path = Path(path).resolve()
    if not path.is_relative_to(WORKSPACE.resolve()):
        raise RuntimeError('Refused DB outside the disposable preview')
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, factory=app_database.ClosingSQLiteConnection, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c


app_database.get_database_connection = local_connection
app_database._secret_value = lambda *args, **kwargs: ''
APP = ROOT / 'ebay_listing_manager' / 'streamlit_app.py'
module = runpy.run_path(str(APP), run_name='stage6_local_preview')
factory = lambda: local_connection(resolve_listing_db_path(APP))
module['init_db']()
backup = WORKSPACE / 'before_stage6.sqlite3'
if not backup.exists():
    with factory() as c, local_connection(backup) as target:
        c.backup(target)
initialize_approval_storage(factory)
catalog = ProductCatalogService(factory)
drafts = ListingDraftService(factory)
service = ApprovalService(factory, calculate_expected=module['calculate_expected_values'], mode='MOCK')
if not catalog.list_products(status='ALL'):
    for n in range(3):
        name = f'Stage6 Camera {n+1}'
        pid = catalog.create_product(dict(product_name=name, sku=f'S6-{n}', category='Cameras',
            country_of_origin='JP', weight_g=500, length_cm=20, width_cm=10, height_cm=5, purchase_price=1000))
        catalog.update_inventory(pid, dict(stock_mode='IN_STOCK', on_hand_quantity=3, reserved_quantity=0))
        did = drafts.create(pid, actor_id='Fixture', price=30)
        drafts.generate(did, expected_revision=1, actor_id='Fixture')
        drafts.update(did, dict(category_id='31388', condition_name='Used', condition_id='3000',
            publication_input_json=json.dumps(dict(exchange_rate=150, shipping_yen=500, shipping_carrier='Japan Post',
                shipping_service='EMS', specifics_reviewed=True))), expected_revision=2, actor_id='Fixture')
        drafts.transition(did, 'READY_FOR_REVIEW', expected_revision=3, actor_id='Fixture')
        drafts.transition(did, 'APPROVED', expected_revision=4, actor_id='Fixture', reviewed=True)
        if n == 0:
            r = service.propose_create(did, actor_id='Fixture', idempotency_key='fixture-create')
            service.approve(r['approval_request_id'], expected_version=r['version'], actor_id='Fixture', reviewed=True)
            published = service.execute(r['approval_request_id'], actor_id='Fixture')
            if published['status'] != 'SUCCEEDED':
                raise RuntimeError('Fixture publication failed')
            for action, changes in (('UPDATE_PRICE', {'price':35}), ('UPDATE_QUANTITY', {'quantity':0}), ('END_LISTING', {})):
                service.propose_change(published['marketplace_listing_id'], action, changes,
                    reason='仕入価格・仕入先状況の手入力テスト。実eBayへは送信しません。',
                    source_status='確認用の申告値・自動監視なし', actor_id='Fixture', actor_type='ai', idempotency_key='fixture-'+action)
# Exercise Cloud's configured-remote UI with all connections still hard-bound to this local DB.
os.environ.update(TURSO_DATABASE_URL='libsql://stage6-preview.invalid', TURSO_AUTH_TOKEN='unused-test-only')
module['main']()
