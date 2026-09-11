"""Additive SQLite/libSQL migrations for the shared system foundation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .draft_migration import create_listing_draft_tables
from .publication_migration import create_publication_tables


ConnectionFactory = Callable[[], Any]


@dataclass(frozen=True)
class Migration:
    migration_id: str
    description: str
    apply: Callable[[Any], None]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _table_exists(connection: Any, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(connection: Any, table_name: str) -> set[str]:
    if not _table_exists(connection, table_name):
        return set()
    return {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table_name})")
    }


def _create_foundation_tables(connection: Any) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            product_id TEXT PRIMARY KEY,
            product_name TEXT NOT NULL,
            platform TEXT NOT NULL,
            sku TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS outbox_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            aggregate_type TEXT NOT NULL,
            aggregate_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            processed_at TEXT,
            idempotency_key TEXT NOT NULL UNIQUE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            audit_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            action TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            actor_id TEXT,
            before_json TEXT,
            after_json TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_products_platform_status "
        "ON products(platform, status)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_outbox_status_created "
        "ON outbox_events(status, created_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_entity_created "
        "ON audit_logs(entity_type, entity_id, created_at)"
    )
    _ensure_legacy_listing_link(connection)


FOUNDATION_MIGRATION = Migration(
    migration_id="0001_integrated_foundation",
    description=(
        "Create products, outbox_events, audit_logs, and the listings product link"
    ),
    apply=_create_foundation_tables,
)


PRODUCT_CATALOG_COLUMNS = {
    "jan": "TEXT NOT NULL DEFAULT ''",
    "ean": "TEXT NOT NULL DEFAULT ''",
    "upc": "TEXT NOT NULL DEFAULT ''",
    "brand": "TEXT NOT NULL DEFAULT ''",
    "model_number": "TEXT NOT NULL DEFAULT ''",
    "category": "TEXT NOT NULL DEFAULT ''",
    "notes": "TEXT NOT NULL DEFAULT ''",
    "country_of_origin": "TEXT NOT NULL DEFAULT ''",
    "hs_code": "TEXT NOT NULL DEFAULT ''",
    "hts_code": "TEXT NOT NULL DEFAULT ''",
    "weight_g": "REAL NOT NULL DEFAULT 0",
    "length_cm": "REAL NOT NULL DEFAULT 0",
    "width_cm": "REAL NOT NULL DEFAULT 0",
    "height_cm": "REAL NOT NULL DEFAULT 0",
    "purchase_price": "REAL NOT NULL DEFAULT 0",
    "purchase_currency": "TEXT NOT NULL DEFAULT 'JPY'",
}


def _create_product_catalog_tables(connection: Any) -> None:
    existing = _table_columns(connection, "products")
    for column, definition in PRODUCT_CATALOG_COLUMNS.items():
        if column not in existing:
            connection.execute(
                f"ALTER TABLE products ADD COLUMN {column} {definition}"
            )

    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_products_identifiers "
        "ON products(jan, ean, upc)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_products_brand_model "
        "ON products(brand, model_number)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS product_sources (
            source_id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_name TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            source_item_id TEXT NOT NULL DEFAULT '',
            price REAL NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT 'JPY',
            stock_status TEXT NOT NULL DEFAULT 'UNKNOWN',
            is_primary INTEGER NOT NULL DEFAULT 0,
            last_checked_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(product_id)
                ON DELETE RESTRICT
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_product_sources_product "
        "ON product_sources(product_id, updated_at)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_product_sources_primary "
        "ON product_sources(product_id) WHERE is_primary = 1"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory (
            product_id TEXT PRIMARY KEY,
            stock_mode TEXT NOT NULL DEFAULT 'IN_STOCK',
            on_hand_quantity INTEGER NOT NULL DEFAULT 0,
            reserved_quantity INTEGER NOT NULL DEFAULT 0,
            reorder_point INTEGER NOT NULL DEFAULT 0,
            storage_location TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(product_id)
                ON DELETE RESTRICT
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_mode "
        "ON inventory(stock_mode, updated_at)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS product_images (
            image_id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL,
            storage_provider TEXT NOT NULL DEFAULT 'external',
            storage_key TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            file_name TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_primary INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(product_id)
                ON DELETE RESTRICT
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_product_images_product "
        "ON product_images(product_id, sort_order, created_at)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_product_images_primary "
        "ON product_images(product_id) WHERE is_primary = 1"
    )


PRODUCT_CATALOG_MIGRATION = Migration(
    migration_id="0002_product_catalog_inventory",
    description=(
        "Extend products and create product sources, inventory, and image metadata"
    ),
    apply=_create_product_catalog_tables,
)

LISTING_DRAFT_MIGRATION = Migration(
    migration_id="0003_listing_drafts",
    description="Create listing drafts and immutable revision history",
    apply=create_listing_draft_tables,
)

LISTING_PUBLICATION_MIGRATION = Migration(
    migration_id="0004_listing_publications",
    description="Add approval snapshots and isolated publication receipts",
    apply=create_publication_tables,
)

MIGRATIONS = (FOUNDATION_MIGRATION, PRODUCT_CATALOG_MIGRATION, LISTING_DRAFT_MIGRATION,
              LISTING_PUBLICATION_MIGRATION)


def _ensure_migration_table(connection: Any) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            migration_id TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def _ensure_legacy_listing_link(connection: Any) -> None:
    """Add only the nullable bridge needed by the existing listings table."""
    columns = _table_columns(connection, "listings")
    if not columns:
        return
    if "product_id" not in columns:
        connection.execute("ALTER TABLE listings ADD COLUMN product_id TEXT")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_listings_product_id "
        "ON listings(product_id)"
    )


def run_schema_migrations(connection_factory: ConnectionFactory) -> tuple[str, ...]:
    """Apply each pending migration once and reconcile the legacy bridge.

    Every migration runs in its own transaction. The listing bridge is also
    checked on every startup so a database bootstrapped before the legacy
    ``listings`` table existed can still be repaired without data backfills.
    """
    with connection_factory() as connection:
        _ensure_migration_table(connection)

    applied: list[str] = []
    for migration in MIGRATIONS:
        with connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            already_applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE migration_id = ?",
                (migration.migration_id,),
            ).fetchone()
            if already_applied is not None:
                continue
            migration.apply(connection)
            connection.execute(
                """
                INSERT INTO schema_migrations (
                    migration_id, description, applied_at
                ) VALUES (?, ?, ?)
                """,
                (migration.migration_id, migration.description, utc_now()),
            )
            applied.append(migration.migration_id)

    with connection_factory() as connection:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_legacy_listing_link(connection)

    return tuple(applied)
