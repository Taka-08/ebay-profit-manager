"""Exercise the legacy-platform guard on isolated SQLite and libSQL databases."""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sqlite3
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

import app_database
from app_database import ClosingSQLiteConnection, RemoteCompatibleConnection
from ebay_listing_manager import streamlit_app as manager


LEGACY = "\u305d\u306e\u4ed6"
EXISTS_SQL = "SELECT 1 FROM listings WHERE platform = ? LIMIT 1"
UPDATE_SQL = "UPDATE listings SET platform = ? WHERE platform = ?"
MANAGER_PATH = Path(manager.__file__).resolve()


class ObservedCursor:
    def __init__(self, cursor, hook):
        self.cursor = cursor
        self.hook = hook

    def fetchall(self):
        rows = self.cursor.fetchall()
        self.hook(rows)
        return rows


class ObservedConnection:
    """Delegate unchanged operations and observe the native transaction state."""

    def __init__(self, connection, events, after_exists=None):
        self.connection = connection
        self.raw = getattr(connection, "_connection", connection)
        self.events = events
        self.after_exists = after_exists

    def execute(self, sql, parameters=()):
        before = self.raw.in_transaction
        cursor = self.connection.execute(sql, parameters)
        self.events.append((sql, parameters, before, self.raw.in_transaction))
        if sql == EXISTS_SQL and self.after_exists is not None:
            return ObservedCursor(cursor, self.after_exists)
        return cursor

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, *args):
        self.events.append(("EXIT", (), self.raw.in_transaction, None))
        return self.connection.__exit__(*args)


class SQLiteManagerInitializationTest(unittest.TestCase):
    driver = "sqlite"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="manager-init-guard-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "listings.sqlite3"
        self.events = []
        self.after_exists = None
        for context in (
            patch.dict(os.environ, {"TURSO_DATABASE_URL": "", "TURSO_AUTH_TOKEN": "",
                                    "EBAY_TOOL_WORKSPACE": temporary.name}),
            patch.object(app_database, "_secret_value", return_value=""),
            patch.object(manager, "get_connection", self.observed_factory),
        ):
            context.start()
            self.addCleanup(context.stop)

    def factory(self):
        if self.driver == "libsql":
            import libsql
            return RemoteCompatibleConnection(libsql.connect(str(self.path)))
        connection = sqlite3.connect(self.path, factory=ClosingSQLiteConnection)
        connection.row_factory = sqlite3.Row
        return connection

    def observed_factory(self):
        return ObservedConnection(self.factory(), self.events, self.after_exists)

    def seed(self, platforms):
        with self.factory() as connection:
            for index, platform in enumerate(platforms, start=1):
                connection.execute(
                    "INSERT INTO listings (product_name, platform, listing_date, status, "
                    "created_at, updated_at, shipping_breakdown_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (f"Synthetic {index}", platform, "2026-09-16", manager.STATUS_ACTIVE,
                     "2026-09-16T00:00:00", "2026-09-16T00:00:00",
                     ' {"base_shipping": ' + str(index * 100) + '} '),
                )

    def rows(self):
        with self.factory() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM listings ORDER BY id")]

    def updates(self):
        return [event for event in self.events if event[0] == UPDATE_SQL]

    def assert_no_write_transaction(self):
        self.assertTrue(self.events)
        self.assertFalse(self.updates())
        self.assertFalse(any(event[0].strip().upper().startswith(
            ("UPDATE", "INSERT", "DELETE", "ALTER", "BEGIN")) for event in self.events))
        self.assertTrue(all(not before and not after for _, _, before, after in self.events))

    def test_new_database_still_initializes_and_runs_following_migrations(self):
        manager.init_db()
        self.assertFalse(self.updates())
        with self.factory() as connection:
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM listings").fetchone()[0])
            self.assertEqual(4, connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0])
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM products").fetchone()[0])
        self.events.clear()
        manager.init_db()
        self.assert_no_write_transaction()

    def test_zero_targets_preserves_all_94_rows_during_repeated_reads(self):
        manager.init_db()
        self.seed([manager.PLATFORM_EBAY, manager.PLATFORM_IPHONE_RESALE] * 47)
        before = self.rows()
        self.events.clear()
        for _ in range(3):
            manager.init_db()
            self.assertEqual(94, len(manager.fetch_listings()))
            self.assertEqual(94, manager.fetch_dashboard()["registered_count"])
        self.assertEqual(9, sum(event[0] == EXISTS_SQL for event in self.events))
        self.assert_no_write_transaction()
        self.assertEqual(before, self.rows())
        self.assertTrue(all(row["product_id"] is None for row in self.rows()))

    def check_conversion(self, platforms):
        manager.init_db()
        self.seed(platforms)
        before = self.rows()
        self.events.clear()
        manager.init_db()
        expected = [dict(row, platform=manager.PLATFORM_IPHONE_RESALE)
                    if row["platform"] == LEGACY else row for row in before]
        self.assertEqual(expected, self.rows())
        self.assertEqual(1, len(self.updates()))
        self.assertEqual((UPDATE_SQL, (manager.PLATFORM_IPHONE_RESALE, LEGACY), False, True),
                         self.updates()[0])
        self.events.clear()
        manager.init_db()
        self.assert_no_write_transaction()

    def test_one_legacy_row_changes_only_platform(self):
        self.check_conversion([LEGACY, manager.PLATFORM_EBAY])

    def test_multiple_legacy_rows_change_only_platform(self):
        self.check_conversion([LEGACY, manager.PLATFORM_EBAY, LEGACY, LEGACY])

    def test_older_database_converts_before_following_migrations(self):
        with self.factory() as connection:
            connection.execute("CREATE TABLE listings (id INTEGER PRIMARY KEY, product_name TEXT, "
                               "platform TEXT, listing_date TEXT, status TEXT, created_at TEXT, updated_at TEXT)")
            connection.execute("INSERT INTO listings VALUES (1, 'Old', ?, '2020-01-01', ?, 'before', 'before')",
                               (LEGACY, manager.STATUS_ACTIVE))
        original_migrations = manager.run_schema_migrations
        observed = []

        def check_order(factory):
            self.assertEqual("EXIT", self.events[-1][0])
            with self.factory() as connection:
                self.assertEqual(manager.PLATFORM_IPHONE_RESALE,
                                 connection.execute("SELECT platform FROM listings").fetchone()[0])
                self.assertIsNone(connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='schema_migrations'").fetchone())
            observed.append(True)
            return original_migrations(factory)

        with patch.object(manager, "run_schema_migrations", side_effect=check_order):
            manager.init_db()
        self.assertEqual([True], observed)
        row = self.rows()[0]
        self.assertEqual((1, "Old", "2020-01-01", "before", "before", None),
                         tuple(row[key] for key in ("id", "product_name", "listing_date",
                                                    "created_at", "updated_at", "product_id")))

    def test_two_overlapping_zero_target_runs_do_not_hold_transactions(self):
        manager.init_db()
        self.seed([manager.PLATFORM_EBAY] * 94)
        before = self.rows()
        barrier = Barrier(2, timeout=10)
        self.after_exists = lambda rows: barrier.wait()
        self.events.clear()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(manager.init_db) for _ in range(2)]
            for future in futures:
                future.result(timeout=20)
        self.assertEqual(2, sum(event[0] == EXISTS_SQL for event in self.events))
        self.assert_no_write_transaction()
        self.assertEqual(before, self.rows())

    def test_existence_read_does_not_block_another_writer(self):
        manager.init_db()
        self.events.clear()
        checked = []

        def competing_writer(rows):
            self.assertFalse(rows)
            with self.factory() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.rollback()
            checked.append(True)

        self.after_exists = competing_writer
        manager.init_db()
        self.assertEqual([True], checked)
        self.assert_no_write_transaction()

    def test_stale_positive_still_respects_existing_where(self):
        manager.init_db()
        self.seed([LEGACY])

        def concurrent_conversion(rows):
            self.assertTrue(rows)
            with self.factory() as connection:
                connection.execute("UPDATE listings SET platform = ? WHERE platform = ?",
                                   (manager.PLATFORM_EBAY, LEGACY))

        self.after_exists = concurrent_conversion
        self.events.clear()
        manager.init_db()
        self.assertEqual(manager.PLATFORM_EBAY, self.rows()[0]["platform"])
        # A stale positive still issues DML: this remaining race is not hidden.
        self.assertEqual(1, len(self.updates()))
        self.assertTrue(self.updates()[0][3])

    def test_stale_negative_is_converted_on_next_init(self):
        manager.init_db()
        self.events.clear()
        self.after_exists = lambda rows: self.seed([LEGACY])
        manager.init_db()
        self.assert_no_write_transaction()
        self.assertEqual(LEGACY, self.rows()[0]["platform"])
        self.after_exists = None
        manager.init_db()
        self.assertEqual(manager.PLATFORM_IPHONE_RESALE, self.rows()[0]["platform"])

    def test_select_error_is_not_treated_as_zero_targets(self):
        manager.init_db()
        self.events.clear()
        original_execute = ObservedConnection.execute

        def fail_exists(connection, sql, parameters=()):
            if sql == EXISTS_SQL:
                raise ValueError("Local SELECT failure")
            return original_execute(connection, sql, parameters)

        with patch.object(ObservedConnection, "execute", fail_exists):
            with self.assertRaisesRegex(ValueError, "Local SELECT failure"):
                manager.init_db()
        self.assertFalse(self.updates())

    def test_manager_startup_and_tab_reruns(self):
        from streamlit.testing.v1 import AppTest

        manager.init_db()
        self.events.clear()
        with patch.object(app_database, "get_database_connection",
                          side_effect=lambda path: self.observed_factory()):
            app = AppTest.from_file(str(MANAGER_PATH)).run(timeout=30)
            self.assertFalse(app.exception)
            for tab in ("\u627f\u8a8d\u30fb\u5b9f\u884c", "\u51fa\u54c1\u7ba1\u7406"):
                # AppTest supplies the selected-tab state, as a browser rerun does.
                app.session_state["manager_main_tab"] = tab
                app.run(timeout=30)
                self.assertFalse(app.exception)
                self.assertEqual(tab, app.session_state["manager_main_tab"])
        self.assertEqual(9, sum(event[0] == EXISTS_SQL for event in self.events))
        self.assert_no_write_transaction()

    def test_manager_reload_starts_fresh_session_without_writes(self):
        from streamlit.testing.v1 import AppTest

        manager.init_db()
        before = self.rows()
        self.events.clear()
        with patch.object(app_database, "get_database_connection",
                          side_effect=lambda path: self.observed_factory()):
            first = AppTest.from_file(str(MANAGER_PATH)).run(timeout=30)
            self.assertFalse(first.exception)
            reloaded = AppTest.from_file(str(MANAGER_PATH)).run(timeout=30)
            self.assertFalse(reloaded.exception)
        self.assertEqual(6, sum(event[0] == EXISTS_SQL for event in self.events))
        self.assert_no_write_transaction()
        self.assertEqual(before, self.rows())


class LibsqlManagerInitializationTest(SQLiteManagerInitializationTest):
    driver = "libsql"


if __name__ == "__main__":
    unittest.main()
