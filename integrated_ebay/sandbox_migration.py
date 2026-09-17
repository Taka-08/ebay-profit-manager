"""Explicit LOCAL opt-in only. Not part of application startup MIGRATIONS."""

MIGRATION_ID = '0006_sandbox_inventory'


def create_sandbox_tables(c):
    c.execute('''CREATE TABLE sandbox_marketplace_listings (
        marketplace_listing_id TEXT PRIMARY KEY,
        product_id TEXT NOT NULL REFERENCES products(product_id),
        listing_draft_id TEXT REFERENCES listing_drafts(listing_draft_id),
        publication_id TEXT REFERENCES listing_publications(publication_id),
        external_listing_id TEXT NOT NULL UNIQUE, sku TEXT NOT NULL, marketplace TEXT NOT NULL,
        mode TEXT NOT NULL CHECK(mode='SANDBOX'), status TEXT NOT NULL,
        current_payload_json TEXT NOT NULL, binding_json TEXT NOT NULL,
        version INTEGER NOT NULL, published_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        approval_request_id TEXT, listing_id INTEGER CHECK(listing_id IS NULL)
    )''')
    c.execute('''CREATE TABLE sandbox_approval_requests (
        approval_request_id TEXT PRIMARY KEY,
        product_id TEXT NOT NULL REFERENCES products(product_id),
        listing_draft_id TEXT REFERENCES listing_drafts(listing_draft_id),
        publication_id TEXT REFERENCES listing_publications(publication_id),
        marketplace_listing_id TEXT NOT NULL REFERENCES sandbox_marketplace_listings(marketplace_listing_id),
        action_type TEXT NOT NULL CHECK(action_type IN ('UPDATE_PRICE','UPDATE_QUANTITY','END_LISTING')),
        mode TEXT NOT NULL CHECK(mode='SANDBOX'),
        status TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED','EXECUTING','SUCCEEDED','FAILED','CANCELLED')),
        proposed_payload_json TEXT NOT NULL, approved_payload_json TEXT, before_payload_json TEXT NOT NULL,
        reason TEXT NOT NULL, source_status TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL, created_actor_type TEXT NOT NULL CHECK(created_actor_type IN ('human','ai','system')),
        approved_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, approved_at TEXT, executed_at TEXT,
        execution_status TEXT NOT NULL DEFAULT 'NOT_QUEUED', error_message TEXT, error_code TEXT,
        attempt_count INTEGER NOT NULL DEFAULT 0, last_attempt_at TEXT,
        reconcile_required INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1,
        idempotency_key TEXT NOT NULL UNIQUE, outbox_event_id TEXT REFERENCES outbox_events(event_id),
        external_listing_id TEXT, result_json TEXT
    )''')
    c.execute('CREATE INDEX idx_sandbox_approval_status ON sandbox_approval_requests(status,created_at)')
    c.execute('''CREATE TABLE sandbox_approval_attempts (
        approval_request_id TEXT NOT NULL REFERENCES sandbox_approval_requests(approval_request_id),
        attempt_number INTEGER NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
        actor_id TEXT NOT NULL, error_code TEXT, error_message TEXT, result_json TEXT,
        PRIMARY KEY(approval_request_id,attempt_number)
    )''')
    # Persist intent before HTTP. A crash at any later point requires readback, never a resend.
    c.execute('''CREATE TABLE sandbox_api_dispatches (
        idempotency_key TEXT PRIMARY KEY,
        approval_request_id TEXT NOT NULL UNIQUE REFERENCES sandbox_approval_requests(approval_request_id),
        marketplace_listing_id TEXT NOT NULL REFERENCES sandbox_marketplace_listings(marketplace_listing_id),
        action_type TEXT NOT NULL, payload_hash TEXT NOT NULL, payload_json TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('INTENT','CONFIRMED','PROJECTED')),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, result_json TEXT
    )''')
    c.execute('''CREATE UNIQUE INDEX uq_sandbox_inflight ON sandbox_api_dispatches(marketplace_listing_id)
        WHERE state != 'PROJECTED' ''')


def sandbox_schema_ready(factory):
    with factory() as c:
        return c.execute("SELECT 1 FROM schema_migrations WHERE migration_id=?", (MIGRATION_ID,)).fetchone() is not None


def initialize_sandbox_storage(factory):
    from app_database import remote_database_is_configured
    from .migrations import Migration, run_schema_migrations
    if remote_database_is_configured():
        raise ValueError('Sandbox基盤はローカル検証DBにのみ明示適用できます。本番Migrationは行いません。')
    # Foundation must already exist; do not initialize or migrate unrelated tables here.
    with factory() as c:
        if not c.execute("SELECT 1 FROM schema_migrations WHERE migration_id='0005_approval_execution'").fetchone():
            raise ValueError('既存の承認基盤が必要です。')
    return run_schema_migrations(factory, migration_set=(Migration(MIGRATION_ID,
        'Isolated Sandbox bindings, approvals and durable API intents', create_sandbox_tables),))
