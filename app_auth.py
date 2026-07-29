"""Authentication gate shared by the Streamlit tools."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Any

import streamlit as st


PASSWORD_ENV = "EBAY_TOOL_PASSWORD"
PASSWORD_HASH_ENV = "EBAY_TOOL_PASSWORD_HASH"
USERNAME_ENV = "EBAY_TOOL_USERNAME"
REQUIRE_AUTH_ENV = "EBAY_REQUIRE_AUTH"

PASSWORD_SECRET = "APP_PASSWORD"
PASSWORD_HASH_SECRET = "APP_PASSWORD_HASH"
USERNAME_SECRET = "APP_USERNAME"
REQUIRE_AUTH_SECRET = "REQUIRE_AUTH"

SESSION_KEY = "_ebay_tool_authenticated"
PBKDF2_ALGORITHM = "pbkdf2_sha256"
INSECURE_PLACEHOLDERS = {
    "change-this-password",
    "change_me",
    "change-me",
    "replace-with-a-long-random-password",
    "replace_with_a_long_random_password",
}


def _secret_value(name: str, group: str | None = None) -> Any:
    try:
        if group:
            section = st.secrets.get(group, {})
            if hasattr(section, "get"):
                grouped_value = section.get(name)
                if grouped_value is not None:
                    return grouped_value
        return st.secrets.get(name)
    except Exception:
        return None


def _setting(
    environment_name: str,
    secret_name: str,
    *,
    group_name: str | None = None,
) -> str:
    environment_value = os.environ.get(environment_name, "").strip()
    if environment_value:
        return environment_value
    secret_value = _secret_value(secret_name, group_name)
    return "" if secret_value is None else str(secret_value).strip()


def _boolean_setting(
    environment_name: str,
    secret_name: str,
    *,
    group_name: str | None = None,
) -> bool | None:
    raw_value = _setting(
        environment_name,
        secret_name,
        group_name=group_name,
    ).casefold()
    if not raw_value:
        return None
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    return None


def configured_username() -> str:
    return (
        _setting(
            USERNAME_ENV,
            USERNAME_SECRET,
            group_name="auth",
        )
        or "admin"
    )


def configured_password() -> str:
    """Return a legacy plaintext password from environment or Secrets."""
    return _setting(
        PASSWORD_ENV,
        PASSWORD_SECRET,
        group_name="auth",
    )


def configured_password_hash() -> str:
    return _setting(
        PASSWORD_HASH_ENV,
        PASSWORD_HASH_SECRET,
        group_name="auth",
    )


def _remote_database_is_configured() -> bool:
    return bool(
        _setting(
            "TURSO_DATABASE_URL",
            "TURSO_DATABASE_URL",
            group_name="database",
        )
    )


def authentication_is_required() -> bool:
    explicit = _boolean_setting(
        REQUIRE_AUTH_ENV,
        REQUIRE_AUTH_SECRET,
        group_name="auth",
    )
    if explicit is not None:
        return explicit

    # A remote database may contain real transaction data. Never expose it
    # accidentally just because the authentication flag was omitted.
    return bool(
        configured_password()
        or configured_password_hash()
        or _remote_database_is_configured()
    )


def _verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded_hash.split(
            "$", 3
        )
        if algorithm != PBKDF2_ALGORITHM:
            return False
        iterations = int(iterations_text)
        if iterations < 100_000:
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected_digest = base64.urlsafe_b64decode(digest_text.encode("ascii"))
    except (TypeError, ValueError):
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual_digest, expected_digest)


def _credentials_are_configured() -> bool:
    plain_password = configured_password()
    password_hash = configured_password_hash()
    if plain_password.casefold() in INSECURE_PLACEHOLDERS:
        return False
    return bool(plain_password or password_hash)


def _credential_fingerprint() -> str:
    configured = configured_password_hash() or hashlib.sha256(
        configured_password().encode("utf-8")
    ).hexdigest()
    return hashlib.sha256(
        f"{configured_username()}\0{configured}".encode("utf-8")
    ).hexdigest()


def _credentials_match(username: str, password: str) -> bool:
    if not hmac.compare_digest(username.strip(), configured_username()):
        return False
    password_hash = configured_password_hash()
    if password_hash:
        return _verify_password(password, password_hash)
    return hmac.compare_digest(password, configured_password())


def require_app_password() -> None:
    """Stop all application rendering until authentication succeeds."""
    if not authentication_is_required():
        return

    if not _credentials_are_configured():
        st.error(
            "認証設定が未完了のため、データを表示できません。"
            "Streamlit SecretsにAPP_USERNAMEとAPP_PASSWORD_HASH"
            "（またはAPP_PASSWORD）を設定してください。"
        )
        st.stop()

    expected_fingerprint = _credential_fingerprint()
    if hmac.compare_digest(
        str(st.session_state.get(SESSION_KEY, "")),
        expected_fingerprint,
    ):
        if st.sidebar.button("ログアウト", key="app_logout", width="stretch"):
            st.session_state.pop(SESSION_KEY, None)
            st.session_state.pop("app_login_password", None)
            st.rerun()
        return

    st.title("ログイン")
    st.caption("認証された利用者だけがこのツールと保存データを利用できます。")
    entered_username = st.text_input(
        "ユーザー名",
        value=configured_username(),
        key="app_login_username",
    )
    entered_password = st.text_input(
        "パスワード",
        type="password",
        key="app_login_password",
    )
    if st.button("ログイン", key="app_login_button", width="stretch"):
        if _credentials_match(entered_username, entered_password):
            st.session_state[SESSION_KEY] = expected_fingerprint
            st.rerun()
        st.error("ユーザー名またはパスワードが正しくありません。")
    st.stop()
