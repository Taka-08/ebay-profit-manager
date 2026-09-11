"""Application services for listing registration and the product catalog."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from contextlib import nullcontext
from typing import Any

from .repositories import (
    AuditLogRepository,
    ListingRepository,
    OutboxEnqueueResult,
    OutboxRepository,
    ProductRepository,
    ProductImageRepository,
    ProductSourceRepository,
    InventoryRepository,
)
from .migrations import utc_now


ConnectionFactory = Callable[[], Any]

PRODUCT_STATUSES = ("ACTIVE", "INACTIVE", "ARCHIVED")
STOCK_MODES = ("IN_STOCK", "DROPSHIP")
PURCHASE_CURRENCIES = ("JPY", "USD", "CAD", "GBP", "AUD")


@dataclass(frozen=True)
class OutboxEventRequest:
    event_type: str
    aggregate_type: str
    payload: Any
    idempotency_key: str
    aggregate_id: str | None = None


@dataclass(frozen=True)
class ListingRegistrationResult:
    product_id: str
    listing_id: int
    outbox_event: OutboxEnqueueResult | None = None


class ListingRegistrationService:
    """Create the product and legacy listing as one atomic operation."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self.connection_factory = connection_factory

    def register(
        self,
        *,
        listing_data: dict[str, Any],
        product_name: str,
        platform: str,
        sku: str = "",
        actor_type: str = "human",
        actor_id: str | None = None,
        audit_metadata: Any = None,
        outbox_event: OutboxEventRequest | None = None,
        product_id: str | None = None,
        connection: Any = None,
    ) -> ListingRegistrationResult:
        if not product_name.strip():
            raise ValueError("product_name is required")
        if "product_id" in listing_data:
            raise ValueError("product_id is managed by ListingRegistrationService")

        owns_transaction = connection is None
        with (self.connection_factory() if owns_transaction else nullcontext(connection)) as connection:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            products = ProductRepository(connection)
            if product_id is None:
                resolved_product_id = products.create(
                    product_name=product_name.strip(),
                    platform=platform,
                    sku=sku.strip(),
                )
            else:
                existing_product = products.get(product_id)
                if existing_product is None:
                    raise ValueError("product_id does not reference an existing product")
                if str(existing_product.get("status") or "").upper() == "ARCHIVED":
                    raise ValueError("Archived products cannot receive new listings")
                resolved_product_id = product_id
            persisted_listing = dict(listing_data)
            persisted_listing["product_id"] = resolved_product_id
            listing_id = ListingRepository(connection).create(persisted_listing)

            AuditLogRepository(connection).append(
                entity_type="listing",
                entity_id=str(listing_id),
                action="listing.registered",
                actor_type=actor_type,
                actor_id=actor_id,
                after={
                    "listing_id": listing_id,
                    "product_id": resolved_product_id,
                    "product_name": product_name.strip(),
                    "platform": platform,
                    "status": listing_data.get("status"),
                },
                metadata=audit_metadata,
            )

            queued_event = None
            if outbox_event is not None:
                aggregate_id = outbox_event.aggregate_id
                if aggregate_id is None:
                    if outbox_event.aggregate_type == "product":
                        aggregate_id = resolved_product_id
                    elif outbox_event.aggregate_type == "listing":
                        aggregate_id = str(listing_id)
                    else:
                        raise ValueError(
                            "aggregate_id is required for non-product/listing events"
                        )
                queued_event = OutboxRepository(connection).enqueue(
                    event_type=outbox_event.event_type,
                    aggregate_type=outbox_event.aggregate_type,
                    aggregate_id=aggregate_id,
                    payload=outbox_event.payload,
                    idempotency_key=outbox_event.idempotency_key,
                )

        return ListingRegistrationResult(
            product_id=resolved_product_id,
            listing_id=listing_id,
            outbox_event=queued_event,
        )


def available_quantity(inventory: dict[str, Any] | None) -> int | None:
    """Return owned stock availability; dropship availability is supplier-driven."""
    if not inventory:
        return 0
    if str(inventory.get("stock_mode") or "IN_STOCK").upper() == "DROPSHIP":
        return None
    return max(
        0,
        int(inventory.get("on_hand_quantity") or 0)
        - int(inventory.get("reserved_quantity") or 0),
    )


class ProductCatalogService:
    """Coordinate product master, sources, inventory, images, and audit history."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self.connection_factory = connection_factory

    @staticmethod
    def _text(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _non_negative(value: Any, field: str) -> float:
        resolved = float(value or 0)
        if resolved < 0:
            raise ValueError(f"{field} must be zero or greater")
        return resolved

    @staticmethod
    def _currency(value: Any) -> str:
        currency = str(value or "JPY").strip().upper()
        if currency not in PURCHASE_CURRENCIES:
            raise ValueError(f"Unsupported currency: {currency}")
        return currency

    @staticmethod
    def _status(value: Any) -> str:
        status = str(value or "ACTIVE").strip().upper()
        if status not in PRODUCT_STATUSES:
            raise ValueError(f"Unsupported product status: {status}")
        return status

    def _product_values(self, values: dict[str, Any]) -> dict[str, Any]:
        product_name = self._text(values.get("product_name"))
        if not product_name:
            raise ValueError("product_name is required")
        return {
            "product_name": product_name,
            "platform": self._text(values.get("platform")) or "eBay",
            "sku": self._text(values.get("sku")),
            "status": self._status(values.get("status")),
            "jan": self._text(values.get("jan")),
            "ean": self._text(values.get("ean")),
            "upc": self._text(values.get("upc")),
            "brand": self._text(values.get("brand")),
            "model_number": self._text(values.get("model_number")),
            "category": self._text(values.get("category")),
            "notes": self._text(values.get("notes")),
            "country_of_origin": self._text(values.get("country_of_origin")).upper(),
            "hs_code": self._text(values.get("hs_code")),
            "hts_code": self._text(values.get("hts_code")),
            "weight_g": self._non_negative(values.get("weight_g"), "weight_g"),
            "length_cm": self._non_negative(values.get("length_cm"), "length_cm"),
            "width_cm": self._non_negative(values.get("width_cm"), "width_cm"),
            "height_cm": self._non_negative(values.get("height_cm"), "height_cm"),
            "purchase_price": self._non_negative(values.get("purchase_price"), "purchase_price"),
            "purchase_currency": self._currency(values.get("purchase_currency")),
        }

    def create_product(
        self,
        values: dict[str, Any],
        *,
        actor_type: str = "human",
        actor_id: str | None = None,
    ) -> str:
        product_values = self._product_values(values)
        with self.connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            product_id = ProductRepository(connection).create(**product_values)
            InventoryRepository(connection).upsert(
                product_id=product_id,
                values={
                    "stock_mode": "IN_STOCK",
                    "on_hand_quantity": 0,
                    "reserved_quantity": 0,
                    "reorder_point": 0,
                    "storage_location": "",
                },
            )
            AuditLogRepository(connection).append(
                entity_type="product",
                entity_id=product_id,
                action="product.created",
                actor_type=actor_type,
                actor_id=actor_id,
                after={"product_id": product_id, **product_values},
            )
        return product_id

    def update_product(
        self,
        product_id: str,
        values: dict[str, Any],
        *,
        actor_type: str = "human",
        actor_id: str | None = None,
    ) -> None:
        product_values = self._product_values(values)
        with self.connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            repository = ProductRepository(connection)
            before = repository.get(product_id)
            if before is None:
                raise ValueError("Product not found")
            product_values["updated_at"] = utc_now()
            repository.update(product_id, product_values)
            AuditLogRepository(connection).append(
                entity_type="product", entity_id=product_id,
                action="product.updated", actor_type=actor_type, actor_id=actor_id,
                before=before, after=repository.get(product_id),
            )

    def archive_product(
        self,
        product_id: str,
        *,
        actor_type: str = "human",
        actor_id: str | None = None,
    ) -> None:
        with self.connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            repository = ProductRepository(connection)
            before = repository.get(product_id)
            if before is None:
                raise ValueError("Product not found")
            repository.update(
                product_id, {"status": "ARCHIVED", "updated_at": utc_now()}
            )
            AuditLogRepository(connection).append(
                entity_type="product", entity_id=product_id,
                action="product.archived", actor_type=actor_type, actor_id=actor_id,
                before=before, after=repository.get(product_id),
            )

    def list_products(self, *, search: str = "", status: str | None = None) -> list[dict[str, Any]]:
        with self.connection_factory() as connection:
            return ProductRepository(connection).list(search=search, status=status)

    def get_product(self, product_id: str) -> dict[str, Any] | None:
        with self.connection_factory() as connection:
            product = ProductRepository(connection).get(product_id)
            if product is None:
                return None
            inventory = InventoryRepository(connection).get(product_id)
            return {
                **product,
                "inventory": inventory,
                "available_quantity": available_quantity(inventory),
                "sources": ProductSourceRepository(connection).list_for_product(product_id),
                "images": ProductImageRepository(connection).list_for_product(product_id),
                "listings": ProductRepository(connection).list_linked_listings(product_id),
            }

    def duplicate_candidates(
        self, values: dict[str, Any], *, exclude_product_id: str | None = None
    ) -> list[dict[str, Any]]:
        with self.connection_factory() as connection:
            return ProductRepository(connection).duplicate_candidates(
                sku=self._text(values.get("sku")), jan=self._text(values.get("jan")),
                ean=self._text(values.get("ean")), upc=self._text(values.get("upc")),
                brand=self._text(values.get("brand")),
                model_number=self._text(values.get("model_number")),
                exclude_product_id=exclude_product_id,
            )

    def add_source(
        self, product_id: str, values: dict[str, Any], *, actor_type: str = "human"
    ) -> str:
        normalized = self._source_values(values)
        with self.connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_product(connection, product_id)
            source_id = ProductSourceRepository(connection).create(
                product_id=product_id, values=normalized
            )
            AuditLogRepository(connection).append(
                entity_type="product_source", entity_id=source_id,
                action="product_source.created", actor_type=actor_type,
                after={"source_id": source_id, "product_id": product_id, **normalized},
            )
        return source_id

    def update_source(
        self, product_id: str, source_id: str, values: dict[str, Any],
        *, actor_type: str = "human"
    ) -> None:
        normalized = self._source_values(values)
        normalized["updated_at"] = utc_now()
        with self.connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            repository = ProductSourceRepository(connection)
            before = repository.get(source_id)
            if before is None or before.get("product_id") != product_id:
                raise ValueError("Product source not found")
            repository.update(source_id, product_id=product_id, values=normalized)
            AuditLogRepository(connection).append(
                entity_type="product_source", entity_id=source_id,
                action="product_source.updated", actor_type=actor_type,
                before=before, after=repository.get(source_id),
            )

    def _source_values(self, values: dict[str, Any]) -> dict[str, Any]:
        source_type = self._text(values.get("source_type")).upper()
        if not source_type:
            raise ValueError("source_type is required")
        return {
            "source_type": source_type,
            "source_name": self._text(values.get("source_name")),
            "source_url": self._text(values.get("source_url")),
            "source_item_id": self._text(values.get("source_item_id")),
            "price": self._non_negative(values.get("price"), "price"),
            "currency": self._currency(values.get("currency")),
            "stock_status": self._text(values.get("stock_status")).upper() or "UNKNOWN",
            "is_primary": bool(values.get("is_primary")),
            "last_checked_at": values.get("last_checked_at") or None,
        }

    def update_inventory(
        self, product_id: str, values: dict[str, Any], *, actor_type: str = "human"
    ) -> None:
        stock_mode = self._text(values.get("stock_mode")).upper() or "IN_STOCK"
        if stock_mode not in STOCK_MODES:
            raise ValueError(f"Unsupported stock mode: {stock_mode}")
        on_hand = int(self._non_negative(values.get("on_hand_quantity"), "on_hand_quantity"))
        reserved = int(self._non_negative(values.get("reserved_quantity"), "reserved_quantity"))
        reorder = int(self._non_negative(values.get("reorder_point"), "reorder_point"))
        if stock_mode == "IN_STOCK" and reserved > on_hand:
            raise ValueError("reserved_quantity cannot exceed on_hand_quantity")
        normalized = {
            "stock_mode": stock_mode,
            "on_hand_quantity": on_hand,
            "reserved_quantity": reserved,
            "reorder_point": reorder,
            "storage_location": self._text(values.get("storage_location")),
            "updated_at": utc_now(),
        }
        with self.connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_product(connection, product_id)
            repository = InventoryRepository(connection)
            before = repository.get(product_id)
            repository.upsert(product_id=product_id, values=normalized)
            after = repository.get(product_id)
            AuditLogRepository(connection).append(
                entity_type="inventory", entity_id=product_id,
                action="inventory.updated", actor_type=actor_type,
                before=before, after={**(after or {}), "available_quantity": available_quantity(after)},
            )

    def add_image(
        self, product_id: str, values: dict[str, Any], *, actor_type: str = "human"
    ) -> str:
        url = self._text(values.get("url"))
        storage_key = self._text(values.get("storage_key"))
        if not url and not storage_key:
            raise ValueError("Either image URL or storage_key is required")
        normalized = {
            "storage_provider": self._text(values.get("storage_provider")) or "external",
            "storage_key": storage_key,
            "url": url,
            "file_name": self._text(values.get("file_name")),
            "sort_order": max(0, int(values.get("sort_order") or 0)),
            "is_primary": bool(values.get("is_primary")),
        }
        with self.connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_product(connection, product_id)
            image_id = ProductImageRepository(connection).create(
                product_id=product_id, values=normalized
            )
            AuditLogRepository(connection).append(
                entity_type="product_image", entity_id=image_id,
                action="product_image.created", actor_type=actor_type,
                after={"image_id": image_id, "product_id": product_id, **normalized},
            )
        return image_id

    @staticmethod
    def _require_product(connection: Any, product_id: str) -> dict[str, Any]:
        product = ProductRepository(connection).get(product_id)
        if product is None:
            raise ValueError("Product not found")
        return product
