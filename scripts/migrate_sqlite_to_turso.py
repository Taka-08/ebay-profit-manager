"""Copy the existing listings table to an empty Turso database."""

from __future__ import annotations

import argparse
import math
import os
import sqlite3
import sys
import tomllib
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = PROJECT_ROOT / "ebay_listing_manager" / "ebay_listings.sqlite3"
DEFAULT_SECRETS = PROJECT_ROOT / ".streamlit" / "secrets.toml"


def read_local_secrets(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def setting(name: str, secrets: dict[str, Any]) -> str:
    environment_value = os.environ.get(name, "").strip()
    if environment_value:
        return environment_value
    database_section = secrets.get("database", {})
    if isinstance(database_section, dict):
        grouped_value = database_section.get(name)
        if grouped_value is not None:
            return str(grouped_value).strip()
    value = secrets.get(name)
    return "" if value is None else str(value).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "既存SQLiteのlistingsをTursoへコピーします。"
            "元のSQLiteファイルは変更しません。"
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="移行元SQLiteファイル",
    )
    parser.add_argument(
        "--secrets-file",
        type=Path,
        default=DEFAULT_SECRETS,
        help="Turso credentials TOML file",
    )
    parser.add_argument(
        "--replace-remote",
        action="store_true",
        help="Turso側の既存listingsを削除してからコピーする",
    )
    return parser.parse_args()


def connect_source(path: Path) -> sqlite3.Connection:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"移行元SQLiteがありません: {resolved}")
    connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def migrated_values_match(source_value: Any, target_value: Any) -> bool:
    if isinstance(source_value, (int, float)) and isinstance(
        target_value, (int, float)
    ):
        return math.isclose(
            float(source_value),
            float(target_value),
            rel_tol=1e-12,
            abs_tol=1e-9,
        )
    return source_value == target_value


def main() -> None:
    args = parse_args()
    secrets = read_local_secrets(args.secrets_file.expanduser().resolve())
    url = setting("TURSO_DATABASE_URL", secrets)
    token = setting("TURSO_AUTH_TOKEN", secrets)
    if not url or not token:
        raise SystemExit(
            "TURSO_DATABASE_URLとTURSO_AUTH_TOKENを環境変数または"
            ".streamlit/secrets.tomlへ設定してください。"
        )

    try:
        import libsql
    except ImportError as exc:
        raise SystemExit(
            "libsqlがありません。先に pip install -r requirements.txt を実行してください。"
        ) from exc

    source = connect_source(args.source)
    target = libsql.connect(database=url, auth_token=token, timeout=30)
    try:
        schema_row = source.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name = 'listings'
            """
        ).fetchone()
        if schema_row is None or not schema_row["sql"]:
            raise RuntimeError("移行元にlistingsテーブルがありません。")

        source_cursor = source.execute("SELECT * FROM listings ORDER BY id")
        columns = tuple(column[0] for column in source_cursor.description)
        rows = [tuple(row[column] for column in columns) for row in source_cursor]

        target.execute(str(schema_row["sql"]))
        target.commit()
        remote_count = int(
            target.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        )
        if remote_count and not args.replace_remote:
            raise RuntimeError(
                f"Turso側に既に{remote_count}件あります。"
                "内容を確認し、置換する場合だけ--replace-remoteを付けてください。"
            )

        target.execute("BEGIN IMMEDIATE")
        if args.replace_remote:
            target.execute("DELETE FROM listings")
        if rows:
            placeholders = ", ".join("?" for _ in columns)
            target.executemany(
                f"INSERT OR REPLACE INTO listings ({', '.join(columns)}) "
                f"VALUES ({placeholders})",
                rows,
            )
        target.commit()

        migrated_count = int(
            target.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        )
        if migrated_count != len(rows):
            raise RuntimeError(
                f"件数が一致しません。SQLite: {len(rows)}件 / "
                f"Turso: {migrated_count}件"
            )
        target_cursor = target.execute("SELECT * FROM listings ORDER BY id")
        target_columns = tuple(
            column[0] for column in target_cursor.description
        )
        target_rows = target_cursor.fetchall()
        if target_columns != columns:
            raise RuntimeError("SQLite and Turso column definitions differ.")
        for row_index, (source_row, target_row) in enumerate(
            zip(rows, target_rows),
            start=1,
        ):
            if not all(
                migrated_values_match(source_value, target_value)
                for source_value, target_value in zip(source_row, target_row)
            ):
                raise RuntimeError(
                    f"SQLite and Turso values differ at row {row_index}."
                )
        print(
            f"移行完了: SQLite {len(rows)}件 -> Turso {migrated_count}件。"
            "元のSQLiteは変更していません。"
        )
    except Exception:
        try:
            target.rollback()
        except Exception:
            pass
        raise
    finally:
        source.close()
        target.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"移行失敗: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
