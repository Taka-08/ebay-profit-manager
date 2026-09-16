"""DB adapter contracts after removal of temporary timing instrumentation."""

import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, call, patch

import app_database
from app_database import (
    CompatibleCursor,
    DatabaseConfigurationError,
    RemoteCompatibleConnection,
    get_database_connection,
)


class DatabaseAdapterTest(unittest.TestCase):
    def setUp(self):
        self.raw = Mock()
        self.connection = RemoteCompatibleConnection(self.raw)
        self.raw_cursor = Mock(description=[("id",), ("name",)])
        self.cursor = CompatibleCursor(self.raw_cursor)

    def test_parameterized_execute_is_forwarded_without_changes(self):
        cursor = self.connection.execute("SELECT ? AS value", (7,))
        self.raw.execute.assert_called_once_with("SELECT ? AS value", (7,))
        self.assertIs(self.raw.execute.return_value, cursor._cursor)

    def test_execute_without_parameters_remains_supported(self):
        self.connection.execute("SELECT 1")
        self.raw.execute.assert_called_once_with("SELECT 1")

    def test_local_pragmas_still_become_empty_selects(self):
        for pragma in ("PRAGMA journal_mode = WAL", "PRAGMA synchronous = NORMAL",
                       "PRAGMA busy_timeout = 30000"):
            with self.subTest(pragma=pragma):
                self.raw.reset_mock()
                self.connection.execute(pragma)
                self.raw.execute.assert_called_once_with("SELECT 1 WHERE 0")

    def test_executemany_is_forwarded_without_changes(self):
        parameters = [(1,), (2,)]
        cursor = self.connection.executemany("INSERT INTO sample VALUES (?)", parameters)
        self.raw.executemany.assert_called_once_with("INSERT INTO sample VALUES (?)", parameters)
        self.assertIs(self.raw.executemany.return_value, cursor._cursor)

    def test_executescript_is_forwarded_without_changes(self):
        cursor = self.connection.executescript("SELECT 1; SELECT 2;")
        self.raw.executescript.assert_called_once_with("SELECT 1; SELECT 2;")
        self.assertIs(self.raw.executescript.return_value, cursor._cursor)

    def test_cursor_factory_keeps_compatible_wrapper(self):
        cursor = self.connection.cursor()
        self.raw.cursor.assert_called_once_with()
        self.assertIs(self.raw.cursor.return_value, cursor._cursor)

    def test_fetchone_returns_named_and_indexed_row_or_none(self):
        self.raw_cursor.fetchone.side_effect = [(1, "one"), None]
        row = self.cursor.fetchone()
        self.assertEqual({"id": 1, "name": "one"}, dict(row))
        self.assertEqual(1, row[0])
        self.assertIsNone(self.cursor.fetchone())

    def test_fetchall_preserves_values_and_column_names(self):
        self.raw_cursor.fetchall.return_value = [(1, "one"), (2, None)]
        self.assertEqual([{"id": 1, "name": "one"}, {"id": 2, "name": None}],
                         [dict(row) for row in self.cursor.fetchall()])

    def test_fetchmany_supports_default_and_explicit_size(self):
        self.raw_cursor.fetchmany.return_value = [(1, "one")]
        self.assertEqual(1, self.cursor.fetchmany()[0]["id"])
        self.assertEqual("one", self.cursor.fetchmany(5)[0]["name"])
        self.assertEqual([call(), call(5)], self.raw_cursor.fetchmany.call_args_list)

    def test_iteration_stops_at_none_without_extra_fetch(self):
        self.raw_cursor.fetchone.side_effect = [(1, "one"), (2, "two"), None]
        self.assertEqual([1, 2], [row["id"] for row in self.cursor])
        self.assertEqual(3, self.raw_cursor.fetchone.call_count)

    def test_metadata_and_cursor_close_are_preserved(self):
        self.raw_cursor.lastrowid = 4
        self.raw_cursor.rowcount = 2
        self.assertEqual(4, self.cursor.lastrowid)
        self.assertEqual(2, self.cursor.rowcount)
        self.assertEqual(self.raw_cursor.description, self.cursor.description)
        self.cursor.close()
        self.raw_cursor.close.assert_called_once_with()

    def test_execute_failure_propagates_and_rolls_back_once(self):
        error = ValueError("Local execute failure")
        self.raw.execute.side_effect = error
        with self.assertRaises(ValueError) as caught:
            with self.connection as connection:
                connection.execute("SELECT 1")
        self.assertIs(error, caught.exception)
        self.assertEqual([call.execute("SELECT 1"), call.rollback(), call.close()],
                         self.raw.mock_calls)

    def test_fetch_failure_propagates_and_rolls_back_once(self):
        error = ValueError("Local fetch failure")
        self.raw.execute.return_value = self.raw_cursor
        self.raw_cursor.fetchall.side_effect = error
        with self.assertRaises(ValueError) as caught:
            with self.connection as connection:
                connection.execute("SELECT 1").fetchall()
        self.assertIs(error, caught.exception)
        self.raw.rollback.assert_called_once_with()
        self.raw.close.assert_called_once_with()
        self.raw.commit.assert_not_called()

    def test_connect_preserves_driver_arguments_without_network(self):
        fake_driver = Mock()
        with patch.object(app_database, "database_setting", side_effect=(
            "libsql://example.invalid", "dummy-test-token"
        )), patch.dict("sys.modules", {"libsql": fake_driver}):
            connection = get_database_connection("unused.sqlite3")
        fake_driver.connect.assert_called_once_with(
            database="libsql://example.invalid", auth_token="dummy-test-token", timeout=30)
        self.assertIs(fake_driver.connect.return_value, connection._connection)

    def test_connect_failure_propagates_without_retry(self):
        fake_driver = Mock()
        error = ValueError("Local connection failure")
        fake_driver.connect.side_effect = error
        with patch.object(app_database, "database_setting", side_effect=(
            "libsql://example.invalid", "dummy-test-token"
        )), patch.dict("sys.modules", {"libsql": fake_driver}):
            with self.assertRaises(ValueError) as caught:
                get_database_connection("unused.sqlite3")
        self.assertIs(error, caught.exception)
        self.assertEqual(1, fake_driver.connect.call_count)

    def test_missing_token_is_rejected_before_driver_connect(self):
        fake_driver = Mock()
        with patch.object(app_database, "database_setting", side_effect=(
            "libsql://example.invalid", ""
        )), patch.dict("sys.modules", {"libsql": fake_driver}):
            with self.assertRaises(DatabaseConfigurationError):
                get_database_connection("unused.sqlite3")
        fake_driver.connect.assert_not_called()

    def test_production_code_has_no_temporary_diagnostic_dependency(self):
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / "db_diagnostics.py").exists())
        for path in (root / "app_database.py", root / "ebay_listing_manager/streamlit_app.py"):
            source = path.read_text(encoding="utf-8")
            for token in ("db_diagnostics", "DBDIAG", "_diagnostic_", "@trace_init", "@trace_run"):
                self.assertNotIn(token, source)

    def test_local_connection_commit_and_rollback_remain_unchanged(self):
        with tempfile.TemporaryDirectory(prefix="db-adapter-") as directory, patch.dict(
            os.environ, {"TURSO_DATABASE_URL": "", "TURSO_AUTH_TOKEN": ""}
        ), patch.object(app_database, "_secret_value", return_value=""):
            path = Path(directory) / "local.sqlite3"
            with get_database_connection(path) as connection:
                connection.execute("CREATE TABLE sample (value INTEGER)")
                connection.execute("INSERT INTO sample VALUES (1)")
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")
            with self.assertRaisesRegex(ValueError, "Rollback this test"):
                with get_database_connection(path) as connection:
                    connection.execute("INSERT INTO sample VALUES (2)")
                    raise ValueError("Rollback this test")
            with get_database_connection(path) as connection:
                self.assertEqual([1], [row[0] for row in connection.execute("SELECT value FROM sample")])

    def test_context_exit_keeps_commit_close_order_and_original_failure(self):
        with self.connection:
            pass
        self.assertEqual([call.commit(), call.close()], self.raw.mock_calls)
        self.raw.reset_mock()
        error = ValueError("Commit failure")
        self.raw.commit.side_effect = error
        with self.assertRaises(ValueError) as caught:
            with self.connection:
                pass
        self.assertIs(error, caught.exception)
        self.assertEqual([call.commit(), call.close()], self.raw.mock_calls)


if __name__ == "__main__":
    unittest.main()
