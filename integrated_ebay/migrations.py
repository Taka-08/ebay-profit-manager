"""Additive SQLite/libSQL migrations for the shared system foundation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


ConnectionFactory = Callable[[], Any]


@dataclass(frozen=True)
class Migration:
    migration_id: str
    description: str
    apply: Callable[[Any], None]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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

MIGRATIONS = (FOUNDATION_MIGRATION,)


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
