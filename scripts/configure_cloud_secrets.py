"""Create ignored Streamlit Community Cloud database Secrets."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SECRETS_PATH = (
    PROJECT_ROOT / ".streamlit" / "community_cloud_secrets.toml"
)


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


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def write_private_file(path: Path, content: str, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"{path} already exists. Pass --force to replace it."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--secrets-path",
        type=Path,
        default=DEFAULT_SECRETS_PATH,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    database_url = normalize_database_url(
        os.environ.get("TURSO_DATABASE_URL", "")
    )
    auth_token = os.environ.get("TURSO_AUTH_TOKEN", "").strip()
    if not auth_token:
        raise SystemExit("TURSO_AUTH_TOKEN is not set.")

    secrets_content = "\n".join(
        (
            "[database]",
            f"TURSO_DATABASE_URL = {toml_string(database_url)}",
            f"TURSO_AUTH_TOKEN = {toml_string(auth_token)}",
            "",
        )
    )

    write_private_file(
        args.secrets_path.resolve(),
        secrets_content,
        overwrite=args.force,
    )
    print(f"Secrets file: {args.secrets_path.resolve()}")
    print("No database URL or token was printed.")


if __name__ == "__main__":
    main()
