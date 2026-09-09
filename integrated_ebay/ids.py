"""Collision-resistant identifiers shared by current and future modules."""

from __future__ import annotations

from types import MappingProxyType
from uuid import uuid4


ENTITY_ID_PREFIXES = MappingProxyType(
    {
        "product": "prd",
        "inventory_item": "inv",
        "profit_calculation": "pft",
        "shipping_quote": "shq",
        "listing_draft": "ldr",
        "approval_request": "apr",
        "marketplace_listing": "mpl",
        "order": "ord",
        "shipment": "shp",
        "task": "tsk",
        "agent_run": "agr",
        "event": "evt",
        "audit": "aud",
    }
)


def generate_entity_id(entity_type: str) -> str:
    """Return a prefixed UUID4 suitable for distributed creation."""
    try:
        prefix = ENTITY_ID_PREFIXES[entity_type]
    except KeyError as exc:
        supported = ", ".join(sorted(ENTITY_ID_PREFIXES))
        raise ValueError(
            f"Unsupported entity type {entity_type!r}. Supported: {supported}"
        ) from exc
    return f"{prefix}_{uuid4().hex}"


def generate_product_id() -> str:
    return generate_entity_id("product")


def generate_event_id() -> str:
    return generate_entity_id("event")


def generate_audit_id() -> str:
    return generate_entity_id("audit")
