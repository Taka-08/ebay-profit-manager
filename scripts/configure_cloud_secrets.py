"""Create ignored Streamlit Community Cloud credentials without printing them."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SECRETS_PATH = (
    PROJECT_ROOT / ".streamlit" / "community_cloud_secrets.toml"
)
DEFAULT_LOGIN_PATH = (
    PROJECT_ROOT / ".streamlit" / "community_cloud_login_credentials.txt"
)
PBKDF2_ITERATIONS = 600_000


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


def make_password_hash(password: str) -> str:
    salt = secrets.token_bytes(24)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return "$".join(
        (
            "pbkdf2_sha256",
            str(PBKDF2_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        )
    )


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
    parser.add_argument("--username", default="admin")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--secrets-path",
        type=Path,
        default=DEFAULT_SECRETS_PATH,
    )
    parser.add_argument(
        "--login-path",
        type=Path,
        default=DEFAULT_LOGIN_PATH,
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

    password = secrets.token_urlsafe(24)
    password_hash = make_password_hash(password)
    secrets_content = "\n".join(
        (
            "[auth]",
            "REQUIRE_AUTH = true",
            f"APP_USERNAME = {toml_string(args.username)}",
            f"APP_PASSWORD_HASH = {toml_string(password_hash)}",
            "",
            "[database]",
            f"TURSO_DATABASE_URL = {toml_string(database_url)}",
            f"TURSO_AUTH_TOKEN = {toml_string(auth_token)}",
            "",
        )
    )
    login_content = "\n".join(
        (
            "Streamlit application login",
            f"Username: {args.username}",
            f"Password: {password}",
            "",
            "Keep this file private. It is ignored by Git.",
            "",
        )
    )

    write_private_file(
        args.secrets_path.resolve(),
        secrets_content,
        overwrite=args.force,
    )
    write_private_file(
        args.login_path.resolve(),
        login_content,
        overwrite=args.force,
    )
    print(f"Secrets file: {args.secrets_path.resolve()}")
    print(f"Login file: {args.login_path.resolve()}")
    print(f"Application username: {args.username}")
    print("No password, token, or password hash was printed.")


if __name__ == "__main__":
    main()
