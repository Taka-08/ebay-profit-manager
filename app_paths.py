"""Shared data-path resolution for the eBay tool suite."""

from __future__ import annotations

import os
from pathlib import Path


WORKSPACE_ENV = "EBAY_TOOL_WORKSPACE"
LISTING_DB_ENV = "EBAY_LISTING_DB_PATH"


def _directory_for(anchor: str | Path) -> Path:
    path = Path(anchor).expanduser().resolve()
    return path if path.is_dir() else path.parent


def resolve_workspace_root(anchor: str | Path) -> Path:
    """Resolve one canonical workspace even when a ZIP copy runs below it."""
    configured = os.environ.get(WORKSPACE_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    start = _directory_for(anchor)
    candidates = (start, *start.parents)

    # The current workspace is named eBay. Prefer it over nested extracted copies.
    for candidate in candidates:
        manager = candidate / "ebay_listing_manager"
        if (
            candidate.name.casefold() == "ebay"
            and (manager / "streamlit_app.py").exists()
            and (candidate / "streamlit_app.py").exists()
        ):
            return candidate

    # Outside the current workspace, keep a standalone extracted package portable.
    for candidate in candidates:
        if (
            (candidate / "streamlit_app.py").exists()
            and (candidate / "ebay_listing_manager" / "streamlit_app.py").exists()
        ):
            return candidate
    return start


def resolve_listing_manager_dir(anchor: str | Path) -> Path:
    return resolve_workspace_root(anchor) / "ebay_listing_manager"


def resolve_listing_db_path(anchor: str | Path) -> Path:
    configured = os.environ.get(LISTING_DB_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return resolve_listing_manager_dir(anchor) / "ebay_listings.sqlite3"


def resolve_exchange_rate_path(anchor: str | Path) -> Path:
    return resolve_listing_manager_dir(anchor) / "exchange_rate.json"


def resolve_registration_event_path(anchor: str | Path) -> Path:
    return resolve_listing_manager_dir(anchor) / "registration_event.json"


def resolve_registration_log_path(anchor: str | Path) -> Path:
    return resolve_listing_manager_dir(anchor) / "logs" / "registration.log"
