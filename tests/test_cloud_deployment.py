from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import app_database


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFIT_APP = PROJECT_ROOT / "streamlit_app.py"
MANAGER_APP = PROJECT_ROOT / "ebay_listing_manager" / "streamlit_app.py"


class CloudDeploymentTest(unittest.TestCase):
    def test_authentication_gate_is_removed_from_both_entry_points(self) -> None:
        for path in (PROFIT_APP, MANAGER_APP):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("app_auth", source)
            self.assertNotIn("require_app_password", source)

    def test_legacy_auth_settings_do_not_block_profit_calculator(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="ebay-no-auth-profit-test-"))
        with patch.dict(
            os.environ,
            {
                "EBAY_TOOL_WORKSPACE": str(workspace),
                "EBAY_REQUIRE_AUTH": "true",
                "EBAY_TOOL_USERNAME": "legacy-user",
                "EBAY_TOOL_PASSWORD": "legacy-password",
                "EBAY_TOOL_PASSWORD_HASH": "legacy-hash",
                "TURSO_DATABASE_URL": "",
                "TURSO_AUTH_TOKEN": "",
            },
            clear=False,
        ):
            app = AppTest.from_file(str(PROFIT_APP)).run(timeout=30)

        self.assertFalse(app.exception)
        self.assertFalse(any(item.label == "ログイン" for item in app.button))
        self.assertFalse(any(item.label == "ユーザー名" for item in app.text_input))
        self.assertFalse(any(item.label == "パスワード" for item in app.text_input))

    def test_legacy_auth_settings_do_not_block_listing_manager(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="ebay-no-auth-manager-test-"))
        with patch.dict(
            os.environ,
            {
                "EBAY_TOOL_WORKSPACE": str(workspace),
                "EBAY_REQUIRE_AUTH": "true",
                "EBAY_TOOL_USERNAME": "legacy-user",
                "EBAY_TOOL_PASSWORD": "legacy-password",
                "EBAY_TOOL_PASSWORD_HASH": "legacy-hash",
                "TURSO_DATABASE_URL": "",
                "TURSO_AUTH_TOKEN": "",
            },
            clear=False,
        ):
            app = AppTest.from_file(str(MANAGER_APP)).run(timeout=30)

        self.assertFalse(app.exception)
        self.assertFalse(any(item.label == "ログイン" for item in app.button))
        self.assertFalse(any(item.label == "ユーザー名" for item in app.text_input))
        self.assertFalse(any(item.label == "パスワード" for item in app.text_input))
        self.assertTrue(
            (workspace / "ebay_listing_manager" / "ebay_listings.sqlite3").exists()
        )

    def test_authentication_dependency_and_secrets_are_removed(self) -> None:
        self.assertFalse((PROJECT_ROOT / "app_auth.py").exists())
        self.assertFalse((PROJECT_ROOT / "scripts" / "generate_password_hash.py").exists())
        for requirements_path in (
            PROJECT_ROOT / "requirements.txt",
            PROJECT_ROOT / "ebay_listing_manager" / "requirements.txt",
        ):
            self.assertNotIn(
                "streamlit-js-eval",
                requirements_path.read_text(encoding="utf-8"),
            )
        example = (
            PROJECT_ROOT / ".streamlit" / "secrets.toml.example"
        ).read_text(encoding="utf-8")
        self.assertNotIn("[auth]", example)
        self.assertNotIn("REQUIRE_AUTH", example)
        self.assertNotIn("APP_USERNAME", example)
        self.assertNotIn("APP_PASSWORD", example)

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
