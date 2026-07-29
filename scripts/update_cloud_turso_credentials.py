"""Update only Turso credentials in an ignored Streamlit Secrets file."""

from __future__ import annotations

import argparse
import json
import os
import tomllib
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SECRETS_PATH = (
    PROJECT_ROOT / ".streamlit" / "community_cloud_secrets.toml"
)


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def normalize_database_url(raw_url: str) -> str:
    value = raw_url.strip()
    if value.startswith("[") and "](" in value:
        value = value[1 : value.index("](")]
    value = value.rstrip("/")
    if value.startswith("https://"):
        value = "libsql://" + value.removeprefix("https://")
    elif value.startswith("http://"):
        value = "libsql://" + value.removeprefix("http://")
    if not value.startswith("libsql://"):
        raise ValueError("TURSO_DATABASE_URL must start with libsql://")
    return value


def require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Missing or invalid [{name}] section.")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--secrets-path",
        type=Path,
        default=DEFAULT_SECRETS_PATH,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    secrets_path = args.secrets_path.expanduser().resolve()
    if not secrets_path.exists():
        raise SystemExit(f"Secrets file does not exist: {secrets_path}")

    current = tomllib.loads(secrets_path.read_text(encoding="utf-8"))
    auth = require_mapping(current.get("auth"), "auth")
    database_url = normalize_database_url(
        os.environ.get("TURSO_DATABASE_URL", "")
    )
    auth_token = os.environ.get("TURSO_AUTH_TOKEN", "").strip()
    if not auth_token:
        raise SystemExit("TURSO_AUTH_TOKEN is not set.")

    auth_lines = ["[auth]"]
    for key in ("REQUIRE_AUTH", "APP_USERNAME", "APP_PASSWORD_HASH"):
        if key not in auth:
            raise ValueError(f"Missing auth setting: {key}")
        value = auth[key]
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = toml_string(str(value))
        auth_lines.append(f"{key} = {rendered}")

    content = "\n".join(
        (
            *auth_lines,
            "",
            "[database]",
            f"TURSO_DATABASE_URL = {toml_string(database_url)}",
            f"TURSO_AUTH_TOKEN = {toml_string(auth_token)}",
            "",
        )
    )
    temporary_path = secrets_path.with_suffix(secrets_path.suffix + ".tmp")
    temporary_path.write_text(content, encoding="utf-8")
    os.replace(temporary_path, secrets_path)
    try:
        os.chmod(secrets_path, 0o600)
    except OSError:
        pass

    print(f"Updated Turso credentials: {secrets_path}")
    print("Authentication settings were preserved.")
    print("No database URL, token, password, or hash was printed.")


if __name__ == "__main__":
    main()
