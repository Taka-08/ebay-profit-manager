"""Temporary instrumentation must not change DB semantics or expose values."""

from concurrent.futures import ThreadPoolExecutor
import json
import unittest
from unittest.mock import Mock, patch

from app_database import RemoteCompatibleConnection, get_database_connection
import db_diagnostics as diag


class DatabaseDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.records = []
        def capture(template, data):
            self.records.append(json.loads(data))
        self.logger = patch.object(diag.LOGGER, "warning", side_effect=capture)
        self.logger.start()
        self.addCleanup(self.logger.stop)

    def test_run_counts_three_inits_with_distinct_operations(self):
        raw = Mock()
        @diag.trace_init
        def init():
            with RemoteCompatibleConnection(raw) as connection:
                connection.execute("UPDATE listings SET platform = ? WHERE platform = ?", ("new", "old"))
        @diag.trace_run
        def main():
            for _ in range(3):
                init()
        main()
        self.assertEqual(3, raw.execute.call_count)
        self.assertEqual(3, raw.commit.call_count)
        self.assertEqual(3, raw.close.call_count)
        self.assertEqual([1, 2, 3], [r['init_no'] for r in self.records if r['event'] == 'init.start'])
        self.assertEqual(3, self.records[-1]['init_count'])
        self.assertEqual(1, len({r['run_id'] for r in self.records}))
        starts = [r['op_id'] for r in self.records if r['event'] == 'op.start']
        self.assertEqual(len(starts), len(set(starts)))
        self.assertTrue(all('utc' in r and 'thread' in r for r in self.records))

    def test_sql_and_params_never_appear(self):
        raw = Mock()
        @diag.trace_init
        def init():
            with RemoteCompatibleConnection(raw) as connection:
                connection.execute("SELECT 'SECRET_SQL_VALUE'", ('SECRET_PARAMETER',))
        init()
        output = json.dumps(self.records)
        self.assertNotIn('SECRET_SQL_VALUE', output)
        self.assertNotIn('SECRET_PARAMETER', output)
        raw.execute.assert_called_once_with("SELECT 'SECRET_SQL_VALUE'", ('SECRET_PARAMETER',))

    def test_commit_error_is_classified_and_propagated_without_retry(self):
        raw = Mock()
        original = ValueError('Hrana: transaction rolled back because stream idle too long SQLITE_BUSY token=SECRET')
        raw.commit.side_effect = original
        @diag.trace_init
        def init():
            with RemoteCompatibleConnection(raw):
                pass
        with self.assertRaises(ValueError) as caught:
            init()
        self.assertIs(original, caught.exception)
        raw.commit.assert_called_once_with()
        raw.close.assert_called_once_with()
        raw.rollback.assert_not_called()
        failure = next(r for r in self.records if r['event'] == 'op.error')
        self.assertEqual('commit', failure['kind'])
        self.assertEqual('turso_idle_rollback', failure['error_category'])
        self.assertNotIn('SECRET', json.dumps(self.records))

    def test_execute_error_and_rollback_are_logged_without_replacing_exception(self):
        raw = Mock()
        original = ValueError('Hrana stream not found: SECRET')
        raw.execute.side_effect = original
        @diag.trace_init
        def init():
            with RemoteCompatibleConnection(raw) as connection:
                connection.execute('SELECT 1')
        with self.assertRaises(ValueError) as caught:
            init()
        self.assertIs(original, caught.exception)
        raw.rollback.assert_called_once_with()
        raw.commit.assert_not_called()
        self.assertTrue(any(r.get('error_category') == 'turso_stream_not_found' for r in self.records))
        self.assertNotIn('SECRET', json.dumps(self.records))

    def test_disabled_and_outside_init_are_silent(self):
        with RemoteCompatibleConnection(Mock()) as connection:
            connection.execute('SELECT 1')
        with patch.object(diag, 'ENABLED', False):
            @diag.trace_run
            @diag.trace_init
            def init():
                with RemoteCompatibleConnection(Mock()) as connection:
                    connection.execute('SELECT 1')
            init()
        self.assertEqual([], self.records)

    def test_context_is_reset_after_error(self):
        @diag.trace_run
        @diag.trace_init
        def init():
            raise ValueError('test')
        with self.assertRaises(ValueError):
            init()
        self.assertIsNone(diag._RUN.get())
        self.assertIsNone(diag._INIT.get())

    def test_concurrent_runs_have_separate_ids_and_counts(self):
        @diag.trace_run
        @diag.trace_init
        def init():
            with diag.operation('execute'):
                pass
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: init(), range(8)))
        ends = [r for r in self.records if r['event'] == 'run.end']
        self.assertEqual(8, len({r['run_id'] for r in ends}))
        self.assertTrue(all(r['init_count'] == 1 for r in ends))

    def test_logging_failure_does_not_break_operation(self):
        raw = Mock()
        with patch.object(diag.LOGGER, 'warning', side_effect=RuntimeError('log failure')):
            @diag.trace_init
            def init():
                with RemoteCompatibleConnection(raw) as connection:
                    connection.execute('SELECT 1')
            init()
        raw.execute.assert_called_once_with('SELECT 1')
        raw.commit.assert_called_once_with()

    def test_connect_failure_does_not_log_credentials(self):
        fake = Mock()
        fake.connect.side_effect = ValueError('SECRET_TOKEN https://SECRET_HOST')
        with patch('app_database.database_setting', side_effect=lambda name: 'libsql://SECRET_HOST' if name.endswith('URL') else 'SECRET_TOKEN'), patch.dict('sys.modules', {'libsql': fake}):
            @diag.trace_init
            def init():
                get_database_connection('not-used.sqlite3')
            with self.assertRaises(ValueError):
                init()
        failure = next(r for r in self.records if r['event'] == 'op.error')
        self.assertEqual('connect', failure['kind'])
        self.assertNotIn('SECRET', json.dumps(self.records))

    def test_fetch_and_pragma_keep_original_behavior(self):
        raw = Mock()
        raw.execute.return_value.description = [('value',)]
        raw.execute.return_value.fetchone.side_effect = [(7,), (8,), None]
        @diag.trace_init
        def init():
            with RemoteCompatibleConnection(raw) as connection:
                cursor = connection.execute('PRAGMA journal_mode = WAL')
                self.assertEqual(7, cursor.fetchone()['value'])
                self.assertEqual([8], [r['value'] for r in cursor])
        init()
        raw.execute.assert_called_once_with('SELECT 1 WHERE 0')
        starts = [r for r in self.records if r['event'] == 'op.start']
        self.assertEqual(['execute', 'fetchone', 'iterate', 'commit', 'close'], [r['kind'] for r in starts])
        self.assertEqual(starts[0]['op_id'], starts[1]['query_id'])

    def test_durations_use_monotonic_clock(self):
        @diag.trace_init
        def init():
            with patch.object(diag, 'perf_counter', side_effect=[10.0, 10.125]):
                with diag.operation('commit'):
                    pass
        init()
        end = next(r for r in self.records if r['event'] == 'op.end')
        self.assertEqual(125.0, end['elapsed_ms'])

    def test_labels_are_fixed_even_for_unknown_sql(self):
        cases = ['CREATE TABLE SECRET_NAME(x)', 'PRAGMA SECRET_NAME', 'SELECT SECRET_VALUE FROM sqlite_master', 'nonsense SECRET']
        for sql in cases:
            self.assertNotIn('SECRET', diag.sql_label(sql))


if __name__ == '__main__':
    unittest.main()
