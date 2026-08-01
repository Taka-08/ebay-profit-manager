from __future__ import annotations

import base64
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import app_auth
import app_database


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANAGER_APP = PROJECT_ROOT / "ebay_listing_manager" / "streamlit_app.py"


def encoded_password(password: str) -> str:
    salt = b"0123456789abcdef"
    iterations = 100_000
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return (
        f"pbkdf2_sha256${iterations}$"
        f"{base64.urlsafe_b64encode(salt).decode('ascii')}$"
        f"{base64.urlsafe_b64encode(digest).decode('ascii')}"
    )


class CloudDeploymentTest(unittest.TestCase):
    def test_password_hash_verification(self) -> None:
        password_hash = encoded_password("correct horse battery staple")
        self.assertTrue(
            app_auth._verify_password(
                "correct horse battery staple",
                password_hash,
            )
        )
        self.assertFalse(app_auth._verify_password("wrong", password_hash))

    def test_browser_session_token_is_signed_and_credential_bound(self) -> None:
        environment = {
            "EBAY_TOOL_USERNAME": "cloud-user",
            "EBAY_TOOL_PASSWORD": "long-test-password",
            "EBAY_TOOL_PASSWORD_HASH": "",
        }
        with patch.dict(os.environ, environment, clear=False):
            token = app_auth._session_token()
            self.assertTrue(app_auth._session_token_is_valid(token))
            self.assertFalse(
                app_auth._session_token_is_valid(f"{token[:-1]}0")
            )

        with patch.dict(
            os.environ,
            {**environment, "EBAY_TOOL_PASSWORD": "changed-password"},
            clear=False,
        ):
            self.assertFalse(app_auth._session_token_is_valid(token))

    def test_browser_session_writer_persists_session_cookie(self) -> None:
        with patch.object(app_auth, "streamlit_js_eval") as js_eval:
            app_auth._write_browser_session("signed-token")

        expression = js_eval.call_args.kwargs["js_expressions"]
        self.assertIn("sessionStorage.setItem", expression)
        self.assertIn("document.cookie", expression)
        self.assertIn("SameSite=Strict", expression)
        self.assertIn("Secure", expression)

    def test_remote_database_requires_authentication(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TURSO_DATABASE_URL": "libsql://example.turso.io",
                "TURSO_AUTH_TOKEN": "test-token",
                "EBAY_REQUIRE_AUTH": "",
                "EBAY_TOOL_PASSWORD": "",
                "EBAY_TOOL_PASSWORD_HASH": "",
            },
            clear=False,
        ):
            with patch.object(app_auth, "_secret_value", return_value=None):
                self.assertTrue(app_auth.authentication_is_required())
                self.assertFalse(app_auth._credentials_are_configured())

    def test_manager_stops_before_data_without_required_credentials(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="ebay-auth-test-"))
        with patch.dict(
            os.environ,
            {
                "EBAY_TOOL_WORKSPACE": str(workspace),
                "EBAY_REQUIRE_AUTH": "true",
                "EBAY_TOOL_PASSWORD": "",
                "EBAY_TOOL_PASSWORD_HASH": "",
                "TURSO_DATABASE_URL": "",
                "TURSO_AUTH_TOKEN": "",
            },
            clear=False,
        ):
            manager = AppTest.from_file(str(MANAGER_APP)).run(timeout=20)

        self.assertFalse(manager.exception)
        self.assertTrue(
            any("認証設定が未完了" in error.value for error in manager.error)
        )
        self.assertFalse(
            any("ダッシュボード" in item.value for item in manager.subheader)
        )
        self.assertFalse(
            (workspace / "ebay_listing_manager" / "ebay_listings.sqlite3").exists()
        )

    def test_manager_login_unlocks_application(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="ebay-login-test-"))
        with patch.dict(
            os.environ,
            {
                "EBAY_TOOL_WORKSPACE": str(workspace),
                "EBAY_REQUIRE_AUTH": "true",
                "EBAY_TOOL_USERNAME": "cloud-user",
                "EBAY_TOOL_PASSWORD": "long-test-password",
                "EBAY_TOOL_PASSWORD_HASH": "",
                "TURSO_DATABASE_URL": "",
                "TURSO_AUTH_TOKEN": "",
            },
            clear=False,
        ):
            manager = AppTest.from_file(str(MANAGER_APP)).run(timeout=20)
            username = next(
                item for item in manager.text_input if item.label == "ユーザー名"
            )
            password = next(
                item for item in manager.text_input if item.label == "パスワード"
            )
            username.set_value("cloud-user")
            password.set_value("long-test-password")
            next(
                item for item in manager.button if item.label == "ログイン"
            ).click()
            manager.run(timeout=20)

        self.assertFalse(manager.exception)
        self.assertTrue(
            any("ダッシュボード" in item.value for item in manager.subheader)
        )
        self.assertTrue(
            (workspace / "ebay_listing_manager" / "ebay_listings.sqlite3").exists()
        )

    def test_valid_request_cookie_skips_login_form_before_render(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="ebay-cookie-auth-test-"))
        environment = {
            "EBAY_TOOL_WORKSPACE": str(workspace),
            "EBAY_REQUIRE_AUTH": "true",
            "EBAY_TOOL_USERNAME": "cloud-user",
            "EBAY_TOOL_PASSWORD": "long-test-password",
            "EBAY_TOOL_PASSWORD_HASH": "",
            "TURSO_DATABASE_URL": "",
            "TURSO_AUTH_TOKEN": "",
        }
        with patch.dict(os.environ, environment, clear=False):
            token = app_auth._session_token()
            with (
                patch.object(app_auth, "_read_browser_cookie", return_value=token),
                patch.object(app_auth, "_write_browser_session"),
                patch.object(app_auth, "_scroll_browser_to_top") as scroll_to_top,
            ):
                manager = AppTest.from_file(str(MANAGER_APP)).run(timeout=20)

        self.assertFalse(manager.exception)
        self.assertFalse(
            any(item.label == "ログイン" for item in manager.button)
        )
        self.assertTrue(
            any("ダッシュボード" in item.value for item in manager.subheader)
        )
        scroll_to_top.assert_called_once_with()

    def test_local_database_remains_sqlite_compatible(self) -> None:
        path = Path(tempfile.mkdtemp(prefix="ebay-db-test-")) / "listings.sqlite3"
        with patch.object(app_database, "_secret_value", return_value=""):
            with patch.dict(
                os.environ,
                {"TURSO_DATABASE_URL": "", "TURSO_AUTH_TOKEN": ""},
                clear=False,
            ):
                with app_database.get_database_connection(path) as connection:
                    connection.execute(
                        "CREATE TABLE sample "
                        "(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)"
                    )
                    cursor = connection.execute(
                        "INSERT INTO sample (name) VALUES (?)",
                        ("local",),
                    )
                    row = connection.execute(
                        "SELECT id, name FROM sample WHERE id = ?",
                        (cursor.lastrowid,),
                    ).fetchone()

        self.assertEqual(dict(row), {"id": 1, "name": "local"})
        self.assertEqual(row[0], 1)
        self.assertEqual(row["name"], "local")

    def test_sensitive_files_are_ignored(self) -> None:
        ignore_text = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in (
            ".streamlit/secrets.toml",
            "*.sqlite3",
            ".env",
            "*.pem",
            "*.key",
        ):
            self.assertIn(pattern, ignore_text)


if __name__ == "__main__":
    unittest.main()
