"""Additive publication storage; preserve stage-4 status CHECK and legacy rows."""


def create_publication_tables(connection):
    columns = {r[1] for r in connection.execute('PRAGMA table_info(listing_drafts)')}
    if 'publication_input_json' not in columns:
        connection.execute("ALTER TABLE listing_drafts ADD COLUMN publication_input_json TEXT NOT NULL DEFAULT '{}'")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS listing_publications (
            publication_id TEXT PRIMARY KEY,
            listing_draft_id TEXT NOT NULL REFERENCES listing_drafts(listing_draft_id),
            product_id TEXT NOT NULL REFERENCES products(product_id),
            approved_revision INTEGER NOT NULL,
            mode TEXT NOT NULL CHECK(mode IN ('MOCK','SANDBOX','LIVE')),
            status TEXT NOT NULL CHECK(status IN ('APPROVED','PUBLISHING','PUBLISHED','FAILED','CANCELLED')),
            sku TEXT NOT NULL COLLATE NOCASE,
            marketplace TEXT NOT NULL,
            currency TEXT NOT NULL,
            final_price REAL NOT NULL,
            quantity INTEGER NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            approved_snapshot_json TEXT NOT NULL,
            listing_payload_json TEXT,
            ebay_item_id TEXT,
            listing_url TEXT,
            listing_id INTEGER REFERENCES listings(id),
            approved_by TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            reconcile_required INTEGER NOT NULL DEFAULT 0,
            error_code TEXT, error_message TEXT, failed_at TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, published_at TEXT,
            UNIQUE(mode, ebay_item_id)
        )
    """)
    for key in ('product_id', 'listing_draft_id', 'sku'):
        connection.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS uq_publication_{key} "
                           f"ON listing_publications({key}) WHERE status <> 'CANCELLED'")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_publications_status ON listing_publications(status, updated_at)")
