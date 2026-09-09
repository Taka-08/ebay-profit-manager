"""Repository primitives shared by SQLite and Turso/libSQL callers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .ids import generate_audit_id, generate_event_id, generate_product_id
from .migrations import utc_now


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _json_value(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _checked_columns(values: dict[str, Any]) -> tuple[str, ...]:
    if not values:
        raise ValueError("At least one column is required")
    columns = tuple(values)
    invalid = [column for column in columns if not _IDENTIFIER.fullmatch(column)]
    if invalid:
        raise ValueError(f"Unsafe SQL column name: {invalid[0]!r}")
    return columns


class ProductRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def create(
        self,
        *,
        product_name: str,
        platform: str,
        sku: str = "",
        status: str = "active",
        product_id: str | None = None,
        timestamp: str | None = None,
    ) -> str:
        created_at = timestamp or utc_now()
        resolved_id = product_id or generate_product_id()
        self.connection.execute(
            """
            INSERT INTO products (
                product_id, product_name, platform, sku,
                created_at, updated_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolved_id,
                product_name,
                platform,
                sku,
                created_at,
                created_at,
                status,
            ),
        )
        return resolved_id

    def get(self, product_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM products WHERE product_id = ?",
            (product_id,),
        ).fetchone()
        return None if row is None else dict(row)


class ListingRepository:
    """Incremental gateway to the existing wide ``listings`` table."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def create(self, values: dict[str, Any]) -> int:
        columns = _checked_columns(values)
        placeholders = ", ".join("?" for _ in columns)
        cursor = self.connection.execute(
            f"INSERT INTO listings ({', '.join(columns)}) VALUES ({placeholders})",
            tuple(values[column] for column in columns),
        )
        return int(cursor.lastrowid)

    def get(self, listing_id: int) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM listings WHERE id = ?",
            (listing_id,),
        ).fetchone()
        return None if row is None else dict(row)

    def count(self) -> int:
        return int(
            self.connection.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        )


@dataclass(frozen=True)
class OutboxEnqueueResult:
    event_id: str
    created: bool


class OutboxRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def enqueue(
        self,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: Any,
        idempotency_key: str,
        event_id: str | None = None,
        timestamp: str | None = None,
    ) -> OutboxEnqueueResult:
        resolved_idempotency_key = idempotency_key.strip()
        if not resolved_idempotency_key:
            raise ValueError("idempotency_key is required")
        created_at = timestamp or utc_now()
        candidate_id = event_id or generate_event_id()
        self.connection.execute(
            """
            INSERT OR IGNORE INTO outbox_events (
                event_id, event_type, aggregate_type, aggregate_id,
                payload_json, status, attempt_count, created_at,
                updated_at, processed_at, idempotency_key
            ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?, NULL, ?)
            """,
            (
                candidate_id,
                event_type,
                aggregate_type,
                aggregate_id,
                _json_value(payload) or "{}",
                created_at,
                created_at,
                resolved_idempotency_key,
            ),
        )
        row = self.connection.execute(
            "SELECT event_id FROM outbox_events WHERE idempotency_key = ?",
            (resolved_idempotency_key,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Outbox event was not persisted")
        persisted_id = str(row[0])
        return OutboxEnqueueResult(
            event_id=persisted_id,
            created=persisted_id == candidate_id,
        )

    def get_by_idempotency_key(self, idempotency_key: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM outbox_events WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        return None if row is None else dict(row)

    def mark_processed(
        self,
        event_id: str,
        *,
        timestamp: str | None = None,
    ) -> None:
        processed_at = timestamp or utc_now()
        self.connection.execute(
            """
            UPDATE outbox_events
            SET status = 'processed', updated_at = ?, processed_at = ?
            WHERE event_id = ?
            """,
            (processed_at, processed_at, event_id),
        )

    def record_failure(
        self,
        event_id: str,
        *,
        timestamp: str | None = None,
    ) -> None:
        self.connection.execute(
            """
            UPDATE outbox_events
            SET status = 'pending', attempt_count = attempt_count + 1,
                updated_at = ?
            WHERE event_id = ?
            """,
            (timestamp or utc_now(), event_id),
        )


class AuditLogRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def append(
        self,
        *,
        entity_type: str,
        entity_id: str,
        action: str,
        actor_type: str,
        actor_id: str | None = None,
        before: Any = None,
        after: Any = None,
        metadata: Any = None,
        audit_id: str | None = None,
        timestamp: str | None = None,
    ) -> str:
        resolved_id = audit_id or generate_audit_id()
        self.connection.execute(
            """
            INSERT INTO audit_logs (
                audit_id, entity_type, entity_id, action,
                actor_type, actor_id, before_json, after_json,
                metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolved_id,
                entity_type,
                entity_id,
                action,
                actor_type,
                actor_id,
                _json_value(before),
                _json_value(after),
                _json_value(metadata),
                timestamp or utc_now(),
            ),
        )
        return resolved_id

    def list_for_entity(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT * FROM audit_logs
            WHERE entity_type = ? AND entity_id = ?
            ORDER BY created_at, audit_id
            """,
            (entity_type, entity_id),
        ).fetchall()
        return [dict(row) for row in rows]
