"""Fixed-value, session-only diagnostics for the Sandbox OAuth callback."""

from contextlib import contextmanager
from contextvars import ContextVar


_CHOICES = {
    "callback_reached": ("NO", "YES"),
    "code_received": ("NO", "YES"),
    "state_received": ("NO", "YES"),
    "stored_state_found": ("NO", "YES"),
    "state_matched": ("NOT CHECKED", "NO", "YES"),
    "state_expired": ("NOT CHECKED", "NO", "YES"),
    "callback_already_processed": ("NO", "YES"),
    "token_exchange_attempted": ("NO", "YES"),
    "token_exchange_http_status": ("NOT ATTEMPTED", "2xx", "4xx", "5xx", "TIMEOUT"),
    "token_exchange_succeeded": ("NOT ATTEMPTED", "NO", "YES"),
    "refresh_token_received": ("NOT CHECKED", "NO", "YES"),
    "query_cleared": ("NO", "YES"),
    "rerun_detected_after_callback": ("NO", "YES"),
    "same_cloud_process": ("UNKNOWN", "SAME", "DIFFERENT"),
}

_ACTIVE = ContextVar("sandbox_oauth_callback_diagnostic", default=None)


def new_diagnostic():
    return {field: choices[0] for field, choices in _CHOICES.items()}


@contextmanager
def diagnostic_scope(diagnostic):
    token = _ACTIVE.set(diagnostic)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def mark(field, value):
    if field not in _CHOICES or value not in _CHOICES[field]:
        raise ValueError("Invalid Sandbox OAuth diagnostic status")
    diagnostic = _ACTIVE.get()
    if diagnostic is not None:
        diagnostic[field] = value


def current_status(field):
    diagnostic = _ACTIVE.get()
    return None if diagnostic is None else diagnostic[field]


def safe_lines(diagnostic):
    return [f"{field.replace('_', ' ')}: "
            f"{value if value in choices else choices[0]}"
            for field, choices in _CHOICES.items()
            for value in (diagnostic.get(field),)]
