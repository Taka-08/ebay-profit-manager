"""Temporary, value-free Cloud diagnostics. Remove after the Stage 6 investigation."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
import logging
from pathlib import PurePath
import re
import sys
from threading import get_ident
from time import perf_counter
from uuid import uuid4


ENABLED = True
LOGGER = logging.getLogger("ebay.db_diagnostics")
INSTANCE = uuid4().hex[:12]
_RUN = ContextVar("db_diagnostic_run", default=None)
_INIT = ContextVar("db_diagnostic_init", default=None)
_SOURCE_FILES = {"app_database.py", "streamlit_app.py", "migrations.py"}


@dataclass
class Run:
    run_id: str
    init_count: int = 0
    operation_count: int = 0


def _site():
    frame = sys._getframe(1)
    sites = []
    while frame:
        name = PurePath(frame.f_code.co_filename).name
        if name in _SOURCE_FILES:
            sites.append(f"{name}:{frame.f_code.co_name}:{frame.f_lineno}")
            if name != "app_database.py" or len(sites) == 3:
                break
        frame = frame.f_back
    return " <- ".join(sites) or "unavailable"


def _error(exc):
    # Never emit exception messages: driver errors can contain SQL, URLs or tokens.
    try:
        message = str(exc).casefold()
    except Exception:
        message = ""
    kind = type(exc).__name__
    if "rolled back" in message and "idle" in message:
        category = "turso_idle_rollback"
    elif "stream not found" in message:
        category = "turso_stream_not_found"
    elif "sqlite_busy" in message or "database is locked" in message:
        category = "sqlite_busy"
    elif "timeout" in message or "timed out" in message:
        category = "timeout"
    elif kind in {"RerunException", "StopException"}:
        category = "streamlit_control"
    else:
        category = "other"
    safe_kind = kind if kind in {"ValueError", "OperationalError", "RuntimeError", "TimeoutError",
                                "RerunException", "StopException", "KeyboardInterrupt"} else "Exception"
    return {"error_type": safe_kind, "error_category": category}


def _emit(event, **fields):
    import json

    try:
        run = _RUN.get()
        record = {"event": event, "utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                  "instance": INSTANCE, "thread": get_ident(),
                  "run_id": run.run_id if run else None, "init_no": _INIT.get(), **fields}
        LOGGER.warning("DBDIAG %s", json.dumps(record, separators=(",", ":")))
    except Exception:
        # Diagnostics must not turn a successful database operation into a failure.
        pass


def sql_label(statement):
    """Return only fixed labels; SQL text, identifiers and values never leave here."""
    sql = " ".join(statement.strip().casefold().split())
    if sql == "update listings set platform = ? where platform = ?":
        return "legacy_platform_update"
    if sql.startswith(("pragma journal_mode", "pragma synchronous", "pragma busy_timeout")):
        return "local_pragma_as_empty_select"
    if sql.startswith("pragma table_info(listings)"):
        return "listings_columns"
    if sql.startswith("create table if not exists listings ("):
        return "listings_create_if_missing"
    if sql == "select migration_id from schema_migrations":
        return "migration_history_read"
    if sql.startswith("select") and "from sqlite_master" in sql:
        return "schema_object_read"
    verb = re.match(r"[a-z]+", sql)
    verb = verb.group() if verb else "other"
    return verb if verb in {"select", "update", "insert", "delete", "create", "alter",
                            "pragma", "begin", "commit", "rollback"} else "other"


@contextmanager
def operation(kind, connection_id=None, label=None, query_id=None):
    run = _RUN.get()
    if not ENABLED or run is None or _INIT.get() is None:
        yield None
        return
    run.operation_count += 1
    op_id = run.operation_count
    fields = {"op_id": op_id, "kind": kind, "connection_id": connection_id, "site": _site()}
    if label is not None:
        fields["sql_label"] = label
    if query_id is not None:
        fields["query_id"] = query_id
    _emit("op.start", **fields)
    started = perf_counter()
    try:
        yield op_id
    except BaseException as exc:
        _emit("op.error", **fields, elapsed_ms=round((perf_counter()-started)*1000, 3), **_error(exc))
        raise
    else:
        _emit("op.end", **fields, elapsed_ms=round((perf_counter()-started)*1000, 3))


def trace_run(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not ENABLED:
            return function(*args, **kwargs)
        run = Run(uuid4().hex)
        token = _RUN.set(run)
        _emit("run.start")
        started = perf_counter()
        try:
            return function(*args, **kwargs)
        except BaseException as exc:
            _emit("run.error", **_error(exc))
            raise
        finally:
            _emit("run.end", init_count=run.init_count,
                  elapsed_ms=round((perf_counter()-started)*1000, 3))
            _RUN.reset(token)
    return wrapped


def trace_init(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not ENABLED:
            return function(*args, **kwargs)
        run = _RUN.get()
        token = None
        if run is None:
            run = Run(uuid4().hex)
            token = _RUN.set(run)
        run.init_count += 1
        init_token = _INIT.set(run.init_count)
        _emit("init.start", caller=_site())
        started = perf_counter()
        try:
            return function(*args, **kwargs)
        except BaseException as exc:
            _emit("init.error", **_error(exc))
            raise
        finally:
            _emit("init.end", elapsed_ms=round((perf_counter()-started)*1000, 3))
            _INIT.reset(init_token)
            if token is not None:
                _RUN.reset(token)
    return wrapped
