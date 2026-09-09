"""Application services that coordinate repositories transactionally."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .repositories import (
    AuditLogRepository,
    ListingRepository,
    OutboxEnqueueResult,
    OutboxRepository,
    ProductRepository,
)


ConnectionFactory = Callable[[], Any]


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
    ) -> ListingRegistrationResult:
        if not product_name.strip():
            raise ValueError("product_name is required")
        if "product_id" in listing_data:
            raise ValueError("product_id is managed by ListingRegistrationService")

        with self.connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            product_id = ProductRepository(connection).create(
                product_name=product_name.strip(),
                platform=platform,
                sku=sku.strip(),
            )
            persisted_listing = dict(listing_data)
            persisted_listing["product_id"] = product_id
            listing_id = ListingRepository(connection).create(persisted_listing)

            AuditLogRepository(connection).append(
                entity_type="listing",
                entity_id=str(listing_id),
                action="listing.registered",
                actor_type=actor_type,
                actor_id=actor_id,
                after={
                    "listing_id": listing_id,
                    "product_id": product_id,
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
                        aggregate_id = product_id
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
            product_id=product_id,
            listing_id=listing_id,
            outbox_event=queued_event,
        )
