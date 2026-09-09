"""Repository primitives shared by SQLite and Turso/libSQL callers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .ids import (
    generate_audit_id,
    generate_event_id,
    generate_image_id,
    generate_product_id,
    generate_source_id,
)
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
        jan: str = "",
        ean: str = "",
        upc: str = "",
        brand: str = "",
        model_number: str = "",
        category: str = "",
        notes: str = "",
        country_of_origin: str = "",
        hs_code: str = "",
        hts_code: str = "",
        weight_g: float = 0,
        length_cm: float = 0,
        width_cm: float = 0,
        height_cm: float = 0,
        purchase_price: float = 0,
        purchase_currency: str = "JPY",
        product_id: str | None = None,
        timestamp: str | None = None,
    ) -> str:
        created_at = timestamp or utc_now()
        resolved_id = product_id or generate_product_id()
        self.connection.execute(
            """
            INSERT INTO products (
                product_id, product_name, platform, sku,
                created_at, updated_at, status,
                jan, ean, upc, brand, model_number, category, notes,
                country_of_origin, hs_code, hts_code,
                weight_g, length_cm, width_cm, height_cm,
                purchase_price, purchase_currency
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolved_id,
                product_name,
                platform,
                sku,
                created_at,
                created_at,
                status,
                jan,
                ean,
                upc,
                brand,
                model_number,
                category,
                notes,
                country_of_origin,
                hs_code,
                hts_code,
                weight_g,
                length_cm,
                width_cm,
                height_cm,
                purchase_price,
                purchase_currency,
            ),
        )
        return resolved_id

    def get(self, product_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM products WHERE product_id = ?",
            (product_id,),
        ).fetchone()
        return None if row is None else dict(row)

    def update(self, product_id: str, values: dict[str, Any]) -> None:
        allowed = {
            "product_name", "platform", "sku", "status", "jan", "ean", "upc",
            "brand", "model_number", "category", "notes", "country_of_origin",
            "hs_code", "hts_code", "weight_g", "length_cm", "width_cm",
            "height_cm", "purchase_price", "purchase_currency", "updated_at",
        }
        invalid = set(values) - allowed
        if invalid:
            raise ValueError(f"Unsupported product column: {sorted(invalid)[0]}")
        columns = _checked_columns(values)
        assignments = ", ".join(f"{column} = ?" for column in columns)
        self.connection.execute(
            f"UPDATE products SET {assignments} WHERE product_id = ?",
            (*[values[column] for column in columns], product_id),
        )

    def list(
        self,
        *,
        search: str = "",
        status: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        parameters: list[Any] = []
        if search.strip():
            like = f"%{search.strip()}%"
            where.append(
                "(product_name LIKE ? OR sku LIKE ? OR jan LIKE ? OR ean LIKE ? "
                "OR upc LIKE ? OR brand LIKE ? OR model_number LIKE ?)"
            )
            parameters.extend([like] * 7)
        if status and status != "ALL":
            where.append("UPPER(status) = ?")
            parameters.append(status.upper())
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        rows = self.connection.execute(
            f"SELECT * FROM products{clause} ORDER BY updated_at DESC, product_id LIMIT ?",
            (*parameters, max(1, int(limit))),
        ).fetchall()
        return [dict(row) for row in rows]

    def duplicate_candidates(
        self,
        *,
        sku: str = "",
        jan: str = "",
        ean: str = "",
        upc: str = "",
        brand: str = "",
        model_number: str = "",
        exclude_product_id: str | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        parameters: list[Any] = []
        for column, raw in (("sku", sku), ("jan", jan), ("ean", ean), ("upc", upc)):
            value = raw.strip()
            if value:
                conditions.append(f"{column} = ?")
                parameters.append(value)
        if brand.strip() and model_number.strip():
            conditions.append("(brand = ? AND model_number = ?)")
            parameters.extend((brand.strip(), model_number.strip()))
        if not conditions:
            return []
        clause = f"({' OR '.join(conditions)})"
        if exclude_product_id:
            clause += " AND product_id <> ?"
            parameters.append(exclude_product_id)
        rows = self.connection.execute(
            f"SELECT product_id, product_name, sku, brand, model_number "
            f"FROM products WHERE {clause} ORDER BY updated_at DESC",
            tuple(parameters),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_linked_listings(self, product_id: str) -> list[dict[str, Any]]:
        table = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'listings'"
        ).fetchone()
        if table is None:
            return []
        columns = {
            str(row[1]) for row in self.connection.execute("PRAGMA table_info(listings)")
        }
        if "product_id" not in columns:
            return []
        selected = ["id", "product_id"]
        for column in ("product_name", "platform", "status", "listing_date"):
            if column in columns:
                selected.append(column)
        rows = self.connection.execute(
            f"SELECT {', '.join(selected)} FROM listings "
            "WHERE product_id = ? ORDER BY id DESC",
            (product_id,),
        ).fetchall()
        return [dict(row) for row in rows]


class ProductSourceRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def create(self, *, product_id: str, values: dict[str, Any]) -> str:
        timestamp = str(values.get("timestamp") or utc_now())
        source_id = str(values.get("source_id") or generate_source_id())
        is_primary = 1 if values.get("is_primary") else 0
        if is_primary:
            self.connection.execute(
                "UPDATE product_sources SET is_primary = 0, updated_at = ? WHERE product_id = ?",
                (timestamp, product_id),
            )
        self.connection.execute(
            """
            INSERT INTO product_sources (
                source_id, product_id, source_type, source_name, source_url,
                source_item_id, price, currency, stock_status, is_primary,
                last_checked_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id, product_id, values["source_type"], values.get("source_name", ""),
                values.get("source_url", ""), values.get("source_item_id", ""),
                values.get("price", 0), values.get("currency", "JPY"),
                values.get("stock_status", "UNKNOWN"), is_primary,
                values.get("last_checked_at"), timestamp, timestamp,
            ),
        )
        return source_id

    def get(self, source_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM product_sources WHERE source_id = ?", (source_id,)
        ).fetchone()
        return None if row is None else dict(row)

    def list_for_product(self, product_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM product_sources WHERE product_id = ? "
            "ORDER BY is_primary DESC, updated_at DESC, source_id",
            (product_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def update(self, source_id: str, *, product_id: str, values: dict[str, Any]) -> None:
        allowed = {
            "source_type", "source_name", "source_url", "source_item_id", "price",
            "currency", "stock_status", "is_primary", "last_checked_at", "updated_at",
        }
        invalid = set(values) - allowed
        if invalid:
            raise ValueError(f"Unsupported source column: {sorted(invalid)[0]}")
        if values.get("is_primary"):
            self.connection.execute(
                "UPDATE product_sources SET is_primary = 0, updated_at = ? "
                "WHERE product_id = ? AND source_id <> ?",
                (values.get("updated_at") or utc_now(), product_id, source_id),
            )
        columns = _checked_columns(values)
        assignments = ", ".join(f"{column} = ?" for column in columns)
        self.connection.execute(
            f"UPDATE product_sources SET {assignments} "
            "WHERE source_id = ? AND product_id = ?",
            (*[values[column] for column in columns], source_id, product_id),
        )


class InventoryRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def get(self, product_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM inventory WHERE product_id = ?", (product_id,)
        ).fetchone()
        return None if row is None else dict(row)

    def upsert(self, *, product_id: str, values: dict[str, Any]) -> None:
        self.connection.execute(
            """
            INSERT INTO inventory (
                product_id, stock_mode, on_hand_quantity, reserved_quantity,
                reorder_point, storage_location, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                stock_mode = excluded.stock_mode,
                on_hand_quantity = excluded.on_hand_quantity,
                reserved_quantity = excluded.reserved_quantity,
                reorder_point = excluded.reorder_point,
                storage_location = excluded.storage_location,
                updated_at = excluded.updated_at
            """,
            (
                product_id, values["stock_mode"], values["on_hand_quantity"],
                values["reserved_quantity"], values["reorder_point"],
                values.get("storage_location", ""), values.get("updated_at") or utc_now(),
            ),
        )


class ProductImageRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def create(self, *, product_id: str, values: dict[str, Any]) -> str:
        image_id = str(values.get("image_id") or generate_image_id())
        is_primary = 1 if values.get("is_primary") else 0
        if is_primary:
            self.connection.execute(
                "UPDATE product_images SET is_primary = 0 WHERE product_id = ?",
                (product_id,),
            )
        self.connection.execute(
            """
            INSERT INTO product_images (
                image_id, product_id, storage_provider, storage_key, url,
                file_name, sort_order, is_primary, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                image_id, product_id, values.get("storage_provider", "external"),
                values.get("storage_key", ""), values.get("url", ""),
                values.get("file_name", ""), values.get("sort_order", 0),
                is_primary, values.get("created_at") or utc_now(),
            ),
        )
        return image_id

    def list_for_product(self, product_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM product_images WHERE product_id = ? "
            "ORDER BY is_primary DESC, sort_order, created_at, image_id",
            (product_id,),
        ).fetchall()
        return [dict(row) for row in rows]


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
