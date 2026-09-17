"""Disposable fake-HTTP browser preview. Never use credentials or a remote DB."""

import os
from pathlib import Path
import re
import runpy
import sqlite3
import sys

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
run = os.environ.get('STAGE7_SANDBOX_PREVIEW_RUN', '')
if not re.fullmatch(r'[A-Za-z0-9_-]+', run):
    raise RuntimeError('A new disposable preview run ID is required')
workspace = ROOT / '.tmp_stage7' / 'sandbox_preview' / run
workspace.mkdir(parents=True, exist_ok=True)
os.environ.update(EBAY_TOOL_WORKSPACE=str(workspace), EBAY_LISTING_DB_PATH='',
                  TURSO_DATABASE_URL='', TURSO_AUTH_TOKEN='', EBAY_EXECUTION_MODE='MOCK')

import app_database
app_database._secret_value = lambda *args: ''
from app_paths import resolve_listing_db_path
from integrated_ebay.approval_migration import initialize_approval_storage
from integrated_ebay.sandbox_migration import initialize_sandbox_storage
from integrated_ebay.sandbox_service import SandboxApprovalService
from integrated_ebay.sandbox_inventory import SandboxInventoryProvider
from integrated_ebay.ebay_api import OAuthSettings
from integrated_ebay.services import ProductCatalogService
from integrated_ebay.sandbox_http import REQUIRED_SCOPES
from test_sandbox_inventory import FakeHTTP, ENV


def connection(path):
    path = Path(path).resolve()
    if not path.is_relative_to(workspace.resolve()):
        raise RuntimeError('Preview refused DB outside disposable workspace')
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, factory=app_database.ClosingSQLiteConnection, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c


app_database.get_database_connection = connection
APP = ROOT / 'ebay_listing_manager' / 'streamlit_app.py'
module = runpy.run_path(str(APP), run_name='sandbox_local_preview')
factory = lambda: connection(resolve_listing_db_path(APP))
module['init_db']()
initialize_approval_storage(factory)
initialize_sandbox_storage(factory)
os.environ.update(ENV)


@st.cache_resource
def fake_http():
    return FakeHTTP()


provider = SandboxInventoryProvider(factory, http=fake_http(),
    settings=OAuthSettings('SANDBOX', access_token='fixture-only-not-a-real-token', scopes=REQUIRED_SCOPES))
service = SandboxApprovalService(factory, provider=provider)
if not service.listings():
    pid = ProductCatalogService(factory).create_product(dict(product_name='Sandbox Contract Preview', sku='MASTER-SKU'))
    mid = service.bind_existing_test_offer(pid, offer_id='1001', item_id='2001', sku='LISTING-SKU',
        marketplace='EBAY_US', currency='USD', actor_id='Fixture', test_target_confirmed=True)
    service.propose_change(mid, 'UPDATE_PRICE', {'price':31.0}, reason='Fake HTTP only; no external traffic',
                           actor_id='Fixture', idempotency_key='preview-price')

# Only the preview's renderer receives the injected fake provider; the real Service is unchanged.
import integrated_ebay.sandbox_service as sandbox_service
original = sandbox_service.SandboxApprovalService
try:
    sandbox_service.SandboxApprovalService = lambda factory: service
    st.caption('FAKE HTTP PREVIEW / not live Sandbox verification')
    module['main']()
finally:
    sandbox_service.SandboxApprovalService = original
