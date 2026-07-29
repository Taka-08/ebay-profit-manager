"""SQLite-compatible database access for local and cloud deployments."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any


TURSO_URL_ENV = "TURSO_DATABASE_URL"
TURSO_TOKEN_ENV = "TURSO_AUTH_TOKEN"


class DatabaseConfigurationError(RuntimeError):
    """Raised when a remote database is only partially configured."""


class ClosingSQLiteConnection(sqlite3.Connection):
    """Commit or roll back like sqlite3, then close the short-lived handle."""

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


class CompatibleRow(Mapping[str, Any]):
    """A small sqlite3.Row-compatible mapping for the libSQL driver."""

    def __init__(self, columns: tuple[str, ...], values: tuple[Any, ...]) -> None:
        self._columns = columns
        self._values = values
        self._indexes = {name: index for index, name in enumerate(columns)}

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return self._values[self._indexes[key]]

    def __iter__(self) -> Iterator[str]:
        return iter(self._columns)

    def __len__(self) -> int:
        return len(self._columns)

    def keys(self) -> tuple[str, ...]:
        return self._columns


class CompatibleCursor:
    """Wrap libSQL tuple rows with named access used by the existing apps."""

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def _columns(self) -> tuple[str, ...]:
        return tuple(column[0] for column in (self._cursor.description or ()))

    def _row(self, row: Any) -> CompatibleRow | None:
        if row is None:
            return None
        return CompatibleRow(self._columns(), tuple(row))

    def fetchone(self) -> CompatibleRow | None:
        return self._row(self._cursor.fetchone())

    def fetchall(self) -> list[CompatibleRow]:
        columns = self._columns()
        return [CompatibleRow(columns, tuple(row)) for row in self._cursor.fetchall()]

    def fetchmany(self, size: int | None = None) -> list[CompatibleRow]:
        rows = (
            self._cursor.fetchmany()
            if size is None
            else self._cursor.fetchmany(size)
        )
        columns = self._columns()
        return [CompatibleRow(columns, tuple(row)) for row in rows]

    def __iter__(self) -> Iterator[CompatibleRow]:
        columns = self._columns()
        while True:
            row = self._cursor.fetchone()
            if row is None:
                break
            yield CompatibleRow(columns, tuple(row))

    @property
    def description(self) -> Any:
        return self._cursor.description

    @property
    def lastrowid(self) -> Any:
        return self._cursor.lastrowid

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    def close(self) -> None:
        self._cursor.close()


class RemoteCompatibleConnection:
    """Expose the subset of sqlite3.Connection used by the applications."""

    _LOCAL_ONLY_PRAGMAS = (
        "pragma busy_timeout",
        "pragma journal_mode",
        "pragma synchronous",
    )

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def execute(
        self,
        statement: str,
        parameters: tuple[Any, ...] | list[Any] | None = None,
    ) -> CompatibleCursor:
        normalized = statement.strip().casefold()
        if normalized.startswith(self._LOCAL_ONLY_PRAGMAS):
            return CompatibleCursor(self._connection.execute("SELECT 1 WHERE 0"))
        cursor = (
            self._connection.execute(statement)
            if parameters is None
            else self._connection.execute(statement, parameters)
        )
        return CompatibleCursor(cursor)

    def executemany(self, statement: str, parameters: Any) -> CompatibleCursor:
        return CompatibleCursor(self._connection.executemany(statement, parameters))

    def executescript(self, script: str) -> CompatibleCursor:
        return CompatibleCursor(self._connection.executescript(script))

    def cursor(self) -> CompatibleCursor:
        return CompatibleCursor(self._connection.cursor())

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> RemoteCompatibleConnection:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()
        return False


def _secret_value(name: str, group: str | None = None) -> str:
    try:
        import streamlit as st

        if group:
            section = st.secrets.get(group, {})
            if hasattr(section, "get"):
                value = section.get(name)
                if value is not None:
                    return str(value).strip()
        value = st.secrets.get(name)
        return "" if value is None else str(value).strip()
    except Exception:
        return ""


def database_setting(name: str) -> str:
    environment_value = os.environ.get(name, "").strip()
    if environment_value:
        return environment_value
    return _secret_value(name, "database")


def remote_database_url() -> str:
    return database_setting(TURSO_URL_ENV)


def remote_database_is_configured() -> bool:
    return bool(remote_database_url())


def database_location_label(local_path: str | Path) -> str:
    if remote_database_is_configured():
        return "Turso Cloud（共有データベース）"
    return str(Path(local_path).expanduser().resolve())


def get_database_connection(local_path: str | Path) -> Any:
    """Connect to Turso when configured, otherwise preserve local SQLite."""
    url = remote_database_url()
    if url:
        token = database_setting(TURSO_TOKEN_ENV)
        if not token:
            raise DatabaseConfigurationError(
                "TURSO_DATABASE_URLは設定されていますが、"
                "TURSO_AUTH_TOKENが設定されていません。"
            )
        try:
            import libsql
        except ImportError as exc:
            raise DatabaseConfigurationError(
                "クラウドDB用のlibsqlがありません。"
                "requirements.txtから依存関係をインストールしてください。"
            ) from exc

        connection = libsql.connect(
            database=url,
            auth_token=token,
            timeout=30,
        )
        return RemoteCompatibleConnection(connection)

    path = Path(local_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        path,
        timeout=30,
        factory=ClosingSQLiteConnection,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection
