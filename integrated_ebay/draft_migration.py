"""Stage 4 only: additive draft storage; no product/listing backfill."""


def create_listing_draft_tables(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS listing_drafts (
            listing_draft_id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL REFERENCES products(product_id) ON DELETE RESTRICT,
            marketplace TEXT NOT NULL DEFAULT 'eBay',
            site TEXT NOT NULL DEFAULT 'EBAY_US',
            status TEXT NOT NULL DEFAULT 'DRAFT'
                CHECK(status IN ('DRAFT','READY_FOR_REVIEW','APPROVED','REJECTED','ARCHIVED')),
            title TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            category_id TEXT, category_name TEXT,
            condition_id TEXT, condition_name TEXT,
            price REAL CHECK(price IS NULL OR price >= 0),
            currency TEXT NOT NULL DEFAULT 'USD',
            quantity INTEGER CHECK(quantity IS NULL OR (quantity >= 0 AND quantity = CAST(quantity AS INTEGER))),
            item_specifics_json TEXT NOT NULL DEFAULT '{}',
            shipping_profile_json TEXT NOT NULL DEFAULT '{}',
            generation_input_json TEXT NOT NULL DEFAULT '{}',
            generation_output_json TEXT NOT NULL DEFAULT '{}',
            review_notes_json TEXT NOT NULL DEFAULT '[]',
            ai_model TEXT, prompt_version TEXT,
            revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
            last_actor_type TEXT NOT NULL DEFAULT 'human',
            created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            approved_at TEXT, approved_by TEXT
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS listing_draft_revisions (
            listing_draft_id TEXT NOT NULL REFERENCES listing_drafts(listing_draft_id) ON DELETE RESTRICT,
            revision INTEGER NOT NULL,
            action TEXT NOT NULL, actor_type TEXT NOT NULL, actor_id TEXT NOT NULL,
            snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(listing_draft_id, revision)
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_listing_drafts_product ON listing_drafts(product_id, updated_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_listing_drafts_status ON listing_drafts(status, updated_at)")
