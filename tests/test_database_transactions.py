"""Regression coverage for Cloud's expired migration-check transactions."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app_database import ClosingSQLiteConnection, RemoteCompatibleConnection
from integrated_ebay import migrations


IDLE_ERROR = (
    'Hrana: SQLite error: interactive transaction was rolled back because '
    'the stream was idle for too long; retry the transaction (SQLITE_BUSY)'
)


class RemoteTransactionCleanupTest(unittest.TestCase):
    def test_success_commits_once_and_closes(self):
        raw = Mock()
        with RemoteCompatibleConnection(raw):
            pass
        raw.commit.assert_called_once_with()
        raw.rollback.assert_not_called()
        raw.close.assert_called_once_with()

    def test_body_failure_rolls_back_and_keeps_original(self):
        raw = Mock()
        error = ValueError(IDLE_ERROR)
        with self.assertRaises(ValueError) as caught:
            with RemoteCompatibleConnection(raw):
                raise error
        self.assertIs(error, caught.exception)
        raw.rollback.assert_called_once_with()
        raw.commit.assert_not_called()
        raw.close.assert_called_once_with()

    def test_server_rollback_does_not_mask_idle_error(self):
        raw = Mock()
        raw.rollback.side_effect = ValueError('cannot rollback - no transaction is active')
        error = ValueError(IDLE_ERROR)
        with self.assertRaises(ValueError) as caught:
            with RemoteCompatibleConnection(raw):
                raise error
        self.assertIs(error, caught.exception)
        self.assertIn('no transaction is active', error.__notes__[0])
        raw.close.assert_called_once_with()

    def test_commit_failure_is_not_ignored_or_retried(self):
        raw = Mock()
        error = ValueError(IDLE_ERROR)
        raw.commit.side_effect = error
        with self.assertRaises(ValueError) as caught:
            with RemoteCompatibleConnection(raw):
                pass
        self.assertIs(error, caught.exception)
        raw.commit.assert_called_once_with()
        raw.close.assert_called_once_with()


class MigrationReadOnlyCheckTest(unittest.TestCase):
    driver = 'sqlite'

    def factory(self):
        if self.driver == 'libsql':
            import libsql
            return RemoteCompatibleConnection(libsql.connect(str(self.path)))
        return sqlite3.connect(self.path, factory=ClosingSQLiteConnection)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='migration-readonly-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'test.sqlite3'
        with self.factory() as c:
            c.execute('CREATE TABLE listings (id INTEGER PRIMARY KEY, '
                      'product_name TEXT, shipping_breakdown_json TEXT)')
            for i in range(94):
                c.execute('INSERT INTO listings VALUES (?, ?, ?)',
                          (i + 1, f'Legacy {i}', ' {"shipping": ' + str(i) + '} '))
        migrations.run_schema_migrations(self.factory)

    def test_applied_checks_are_read_only_and_keep_94_rows(self):
        statements = []
        with self.factory() as c:
            before = [tuple(r[i] for i in range(len(r)))
                      for r in c.execute('SELECT * FROM listings ORDER BY id')]

        def guarded_factory():
            c = self.factory()
            execute = c.execute

            class Guard:
                def execute(self, sql, *args):
                    statements.append(sql)
                    # Reproduce the failure if the old redundant BEGIN returns.
                    if sql.strip().upper().startswith('BEGIN'):
                        raise ValueError(IDLE_ERROR)
                    if not sql.strip().upper().startswith(('SELECT', 'PRAGMA')):
                        raise AssertionError('Applied checks must not write: ' + sql)
                    return execute(sql, *args)

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return c.__exit__(*args)

            return Guard()

        self.assertEqual((), migrations.run_schema_migrations(guarded_factory))
        self.assertTrue(statements)
        with self.factory() as c:
            after = [tuple(r[i] for i in range(len(r)))
                     for r in c.execute('SELECT * FROM listings ORDER BY id')]
            self.assertEqual(4, c.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0])
        self.assertEqual(before, after)
        self.assertEqual(94, len(after))
        self.assertTrue(all(r[-1] is None for r in after))

    def test_bridge_for_late_legacy_table_remains_supported(self):
        self.path = Path(self.temp.name) / 'late-listings.sqlite3'
        self.assertEqual(4, len(migrations.run_schema_migrations(self.factory)))
        with self.factory() as c:
            c.execute('CREATE TABLE listings (id INTEGER PRIMARY KEY, product_name TEXT)')
            c.execute("INSERT INTO listings VALUES (1, 'Legacy')")
        self.assertEqual((), migrations.run_schema_migrations(self.factory))
        with self.factory() as c:
            row = c.execute('SELECT * FROM listings').fetchone()
            self.assertEqual((1, 'Legacy', None), tuple(row[i] for i in range(len(row))))
            self.assertIsNotNone(c.execute("SELECT 1 FROM sqlite_master WHERE name='idx_listings_product_id'").fetchone())

    def test_missing_bridge_index_is_reconciled_without_backfill(self):
        with self.factory() as c:
            c.execute('DROP INDEX idx_listings_product_id')
        self.assertEqual((), migrations.run_schema_migrations(self.factory))
        with self.factory() as c:
            self.assertIsNotNone(c.execute("SELECT 1 FROM sqlite_master WHERE name='idx_listings_product_id'").fetchone())
            self.assertEqual(94, c.execute('SELECT COUNT(*) FROM listings WHERE product_id IS NULL').fetchone()[0])

    def test_pending_migration_is_rechecked_under_lock(self):
        calls = []
        migration = migrations.Migration('test_race', 'Local test only', lambda c: calls.append('apply'))
        opened = 0

        def racing_factory():
            nonlocal opened
            opened += 1
            if opened == 2:
                # A second process finishes after the first process's read check.
                migrations.run_schema_migrations(self.factory)
            return self.factory()

        with patch.object(migrations, 'MIGRATIONS', (*migrations.MIGRATIONS, migration)):
            self.assertEqual((), migrations.run_schema_migrations(racing_factory))
        self.assertEqual(['apply'], calls)
        with self.factory() as c:
            self.assertEqual(1, c.execute("SELECT COUNT(*) FROM schema_migrations WHERE migration_id='test_race'").fetchone()[0])

    def test_failed_pending_migration_rolls_back(self):
        def fail(c):
            c.execute('CREATE TABLE incomplete (id INTEGER)')
            raise ValueError('Test failure')

        migration = migrations.Migration('test_failure', 'Local test only', fail)
        with patch.object(migrations, 'MIGRATIONS', (*migrations.MIGRATIONS, migration)):
            with self.assertRaisesRegex(ValueError, 'Test failure'):
                migrations.run_schema_migrations(self.factory)
        with self.factory() as c:
            self.assertIsNone(c.execute("SELECT 1 FROM sqlite_master WHERE name='incomplete'").fetchone())
            self.assertIsNone(c.execute("SELECT 1 FROM schema_migrations WHERE migration_id='test_failure'").fetchone())


class LibsqlMigrationReadOnlyCheckTest(MigrationReadOnlyCheckTest):
    driver = 'libsql'


if __name__ == '__main__':
    unittest.main()
