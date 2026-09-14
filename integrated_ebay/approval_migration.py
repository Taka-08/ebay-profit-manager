"""Stage 6 is opt-in: never migrate a configured production database at startup."""


MIGRATION_ID = '0005_approval_execution'


def create_approval_tables(c):
    c.execute('''CREATE TABLE IF NOT EXISTS approval_requests (
        approval_request_id TEXT PRIMARY KEY,
        product_id TEXT NOT NULL REFERENCES products(product_id),
        listing_draft_id TEXT REFERENCES listing_drafts(listing_draft_id),
        publication_id TEXT REFERENCES listing_publications(publication_id),
        marketplace_listing_id TEXT,
        action_type TEXT NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('MOCK','DRY_RUN')),
        status TEXT NOT NULL CHECK(status IN
          ('PENDING','APPROVED','REJECTED','EXECUTING','SUCCEEDED','FAILED','CANCELLED')),
        proposed_payload_json TEXT NOT NULL,
        approved_payload_json TEXT,
        before_payload_json TEXT NOT NULL,
        reason TEXT NOT NULL,
        source_status TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL,
        created_actor_type TEXT NOT NULL CHECK(created_actor_type IN ('human','ai','system')),
        approved_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        approved_at TEXT, executed_at TEXT,
        execution_status TEXT NOT NULL DEFAULT 'NOT_QUEUED',
        error_message TEXT, error_code TEXT,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        last_attempt_at TEXT,
        reconcile_required INTEGER NOT NULL DEFAULT 0,
        version INTEGER NOT NULL DEFAULT 1,
        idempotency_key TEXT NOT NULL UNIQUE,
        outbox_event_id TEXT REFERENCES outbox_events(event_id),
        external_listing_id TEXT,
        result_json TEXT
    )''')
    c.execute('''CREATE UNIQUE INDEX IF NOT EXISTS uq_approval_create_active
        ON approval_requests(product_id,mode) WHERE action_type='CREATE_LISTING'
        AND status NOT IN ('REJECTED','CANCELLED')''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status,created_at)')
    c.execute('''CREATE TABLE IF NOT EXISTS approval_execution_attempts (
        approval_request_id TEXT NOT NULL REFERENCES approval_requests(approval_request_id),
        attempt_number INTEGER NOT NULL,
        status TEXT NOT NULL,
        started_at TEXT NOT NULL, finished_at TEXT,
        actor_id TEXT NOT NULL, error_code TEXT, error_message TEXT, result_json TEXT,
        PRIMARY KEY(approval_request_id,attempt_number)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS marketplace_listings (
        marketplace_listing_id TEXT PRIMARY KEY,
        product_id TEXT NOT NULL REFERENCES products(product_id),
        listing_draft_id TEXT NOT NULL REFERENCES listing_drafts(listing_draft_id),
        publication_id TEXT NOT NULL UNIQUE REFERENCES listing_publications(publication_id),
        listing_id INTEGER REFERENCES listings(id),
        approval_request_id TEXT NOT NULL REFERENCES approval_requests(approval_request_id),
        external_listing_id TEXT NOT NULL UNIQUE,
        sku TEXT NOT NULL,
        marketplace TEXT NOT NULL,
        mode TEXT NOT NULL CHECK(mode='MOCK'),
        status TEXT NOT NULL,
        current_payload_json TEXT NOT NULL,
        version INTEGER NOT NULL,
        published_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_marketplace_product ON marketplace_listings(product_id)')
    c.execute('''CREATE TABLE IF NOT EXISTS ebay_mock_listings (
        external_listing_id TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL,
        status TEXT NOT NULL,
        version INTEGER NOT NULL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS ebay_mock_receipts (
        idempotency_key TEXT PRIMARY KEY,
        action_type TEXT NOT NULL,
        payload_hash TEXT NOT NULL,
        result_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )''')


def approval_schema_ready(factory):
    with factory() as c:
        return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='approval_requests'").fetchone() is not None


def initialize_approval_storage(factory):
    from app_database import remote_database_is_configured
    from .migrations import MIGRATIONS, Migration, run_schema_migrations
    if remote_database_is_configured():
        raise ValueError('第6段階の本番Migrationは、バックアップと別途承認が必要です。')
    return run_schema_migrations(factory, migration_set=(*MIGRATIONS,
        Migration(MIGRATION_ID, 'Approval queue, execution history and isolated Mock receipts', create_approval_tables)))
