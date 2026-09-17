"""Stage 7 safety matrix against isolated SQLite/libSQL; never remote eBay/DB."""

import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import test_approval_execution as fixtures
from integrated_ebay.approval_service import ApprovalService
from integrated_ebay.draft_repository import encode
from integrated_ebay.publication_provider import PublicationError


class ListingChangeTests(unittest.TestCase):
    driver = 'sqlite'
    setUp = fixtures.ApprovalExecutionTests.setUp
    tearDown = fixtures.ApprovalExecutionTests.tearDown
    factory = fixtures.ApprovalExecutionTests.factory
    rows = fixtures.ApprovalExecutionTests.rows
    edit = fixtures.ApprovalExecutionTests.edit
    transition = fixtures.ApprovalExecutionTests.transition
    proposal = fixtures.ApprovalExecutionTests.proposal
    approve = fixtures.ApprovalExecutionTests.approve
    execute = fixtures.ApprovalExecutionTests.execute
    publish = fixtures.ApprovalExecutionTests.publish
    change = fixtures.ApprovalExecutionTests.change

    def approved_change(self, action='UPDATE_PRICE', changes=None):
        pub = self.publish()
        row = self.approve(self.change(pub, action, {'price':35} if changes is None else changes),
                           end_confirmed=action == 'END_LISTING')
        return pub, row

    def remote_edit(self, pub, changes=None, *, status='ACTIVE', bump=True):
        state = self.mock.get_listing(pub['external_listing_id'])
        state['payload'].update(changes or {})
        with self.factory() as c:
            c.execute('UPDATE ebay_mock_listings SET payload_json=?,status=?,version=? WHERE external_listing_id=?',
                (encode(state['payload']), status, state['version'] + int(bump), pub['external_listing_id']))

    def test_success_price_quantity_zero_and_end_preserve_94_rows(self):
        pub = self.publish()
        for n, (action, changes) in enumerate((('UPDATE_PRICE', {'price':35.19}),
                ('UPDATE_QUANTITY', {'quantity':2}), ('UPDATE_QUANTITY', {'quantity':0}), ('END_LISTING', {}))):
            row = self.approve(self.change(pub, action, changes, str(n)), end_confirmed=action=='END_LISTING')
            before = self.rows('marketplace_listings')[0]
            done = self.execute(row)
            self.assertEqual('SUCCEEDED', done['status'], done)
            result = json.loads(done['result_json'])
            self.assertEqual('ENDED' if action=='END_LISTING' else 'ACTIVE', result['status'])
            self.assertEqual(before['current_payload_json'], row['before_payload_json'])
            self.assertEqual(result, self.mock.get_listing(pub['external_listing_id']))
        self.assertEqual(self.legacy, self.rows('listings'))
        self.assertEqual(94, len(self.rows('listings')))

    def test_freezes_identity_currency_before_after_and_actor(self):
        pub, row = self.approved_change()
        payload = json.loads(row['approved_payload_json'])
        self.assertEqual(self.pid, payload['target']['product_id'])
        self.assertEqual(pub['external_listing_id'], payload['target']['external_listing_id'])
        self.assertEqual('USD', payload['target']['currency'])
        self.assertEqual(30, payload['expected_before']['price'])
        self.assertEqual(35, payload['changes']['price'])
        self.assertEqual('Human', row['approved_by'])
        self.assertTrue(row['approved_at'])

    def test_remote_changed_after_approval_stops_before_write(self):
        pub, row = self.approved_change()
        self.remote_edit(pub, {'price':99})
        with patch.object(self.mock, 'update_price', side_effect=AssertionError('Must not dispatch')) as send:
            failed = self.execute(row)
        send.assert_not_called()
        self.assertEqual('STALE', failed['error_code'])
        self.assertEqual(0, failed['reconcile_required'])
        self.assertIn('送信していません', failed['error_message'])
        self.assertEqual(30, json.loads(self.rows('marketplace_listings')[0]['current_payload_json'])['price'])

    def test_remote_currency_sku_marketplace_mismatch_without_revision_change(self):
        pub = self.publish()
        original = self.mock.get_listing(pub['external_listing_id'])
        for n, change in enumerate(({'currency':'CAD'}, {'sku':'OTHER'}, {'site':'OTHER_MARKET'}, {'price':80})):
            with self.subTest(change=change):
                row = self.approve(self.change(pub, 'UPDATE_PRICE', {'price':35+n}, str(n)))
                self.remote_edit(pub, change, bump=False)
                with patch.object(self.mock, 'update_price') as send:
                    failed = self.execute(row)
                send.assert_not_called()
                self.assertEqual('STALE', failed['error_code'])
                with self.factory() as c:
                    c.execute('UPDATE ebay_mock_listings SET payload_json=?', (encode(original['payload']),))

    def test_already_ended_stops_before_write(self):
        pub, row = self.approved_change('END_LISTING', {})
        self.remote_edit(pub, status='ENDED')
        with patch.object(self.mock, 'end_listing') as send:
            failed = self.execute(row)
        send.assert_not_called()
        self.assertEqual('STALE', failed['error_code'])

    def test_local_binding_tamper_stops_even_with_same_revision(self):
        pub, row = self.approved_change()
        with self.factory() as c:
            c.execute("UPDATE marketplace_listings SET external_listing_id='MOCK-wrong'")
        with patch.object(self.mock, 'update_price') as send:
            failed = self.execute(row)
        send.assert_not_called()
        self.assertEqual('STALE', failed['error_code'])

    def test_ambiguous_product_sku_blocks_approval(self):
        pub = self.publish()
        row = self.change(pub, 'UPDATE_PRICE', {'price':35})
        with self.factory() as c:
            c.execute("UPDATE products SET sku='different' WHERE product_id=?", (self.pid,))
        with self.assertRaises(ValueError):
            self.approve(row)

    def test_old_pending_without_frozen_binding_requires_reproposal(self):
        pub = self.publish()
        row = self.change(pub, 'UPDATE_PRICE', {'price':35})
        payload = json.loads(row['proposed_payload_json'])
        del payload['target']
        del payload['expected_before']
        with self.factory() as c:
            c.execute('UPDATE approval_requests SET proposed_payload_json=? WHERE approval_request_id=?',
                      (encode(payload), row['approval_request_id']))
        with self.assertRaises(ValueError):
            self.approve(row)
        cancelled = self.service.cancel(row['approval_request_id'], expected_version=row['version'], actor_id='Human')
        self.assertEqual('CANCELLED', cancelled['status'])
        fresh = self.approve(self.change(pub, 'UPDATE_PRICE', {'price':35}, 'replacement'))
        self.assertEqual('SUCCEEDED', self.execute(fresh)['status'])

    def test_invalid_quantity_and_money_never_create_request(self):
        pub = self.publish()
        for value in (None, True, -1, 0.5, '0', 2_147_483_648):
            with self.subTest(quantity=value), self.assertRaises(ValueError):
                self.change(pub, 'UPDATE_QUANTITY', {'quantity':value}, str(value))
        for value in (None, True, -1, 0, 1.001, float('inf'), 1e308):
            with self.subTest(price=value), self.assertRaises(ValueError):
                self.change(pub, 'UPDATE_PRICE', {'price':value}, str(value))
        self.assertEqual(1, len(self.rows('approval_requests')))

    def test_duplicate_proposals_different_keys_and_concurrent_approval_execution(self):
        pub = self.publish()
        with ThreadPoolExecutor(2) as pool:
            rows = list(pool.map(lambda key: self.change(pub, 'UPDATE_PRICE', {'price':35}, key), ('tab-a','tab-b')))
        self.assertEqual(rows[0]['approval_request_id'], rows[1]['approval_request_id'])
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(self.approve, rows))
        def run(_):
            try:
                return self.execute(rows[0])['status']
            except ValueError:
                return 'BUSY'
        with ThreadPoolExecutor(2) as pool:
            self.assertIn('SUCCEEDED', list(pool.map(run, range(2))))
        self.assertEqual(2, len(self.rows('ebay_mock_receipts')))
        self.assertEqual(2, len(self.rows('outbox_events')))
        self.assertEqual(1, self.service.get(rows[0]['approval_request_id'])['attempt_count'])

    def test_preflight_write_race_rechecked_inside_mock_transaction(self):
        pub, row = self.approved_change()
        original = self.mock.update_price
        def concurrent_edit(payload, **kwargs):
            self.remote_edit(pub, {'price':77}, bump=False)
            return original(payload, **kwargs)
        with patch.object(self.mock, 'update_price', side_effect=concurrent_edit):
            failed = self.execute(row)
        self.assertEqual('STALE', failed['error_code'])
        self.assertEqual(77, self.mock.get_listing(pub['external_listing_id'])['payload']['price'])
        self.assertEqual(1, len(self.rows('ebay_mock_receipts')))

    def test_auth_rate_limit_and_known_rejection_keep_before_values(self):
        pub = self.publish()
        for n, code in enumerate(('AUTH_EXPIRED', 'RATE_LIMIT', 'FAILED')):
            row = self.approve(self.change(pub, 'UPDATE_PRICE', {'price':35+n}, str(n)))
            before = self.rows('marketplace_listings')
            with patch.object(self.mock, 'update_price', side_effect=PublicationError(code, 'secret-do-not-store')):
                failed = self.execute(row)
            self.assertEqual(code, failed['error_code'])
            self.assertEqual(0, failed['reconcile_required'])
            self.assertEqual(before, self.rows('marketplace_listings'))
            self.assertNotIn('secret-do-not-store', str(self.rows('audit_logs')))
            self.assertEqual('SUCCEEDED', self.execute(row)['status'])

    def test_read_failure_is_not_an_unknown_write(self):
        pub, row = self.approved_change()
        with patch.object(self.mock, 'get_listing', side_effect=TimeoutError('secret')), patch.object(self.mock, 'update_price') as send:
            failed = self.execute(row)
        send.assert_not_called()
        self.assertEqual('READ_FAILED', failed['error_code'])
        self.assertEqual(0, failed['reconcile_required'])
        self.assertEqual('SUCCEEDED', self.execute(row)['status'])

    def test_timeout_after_write_restarts_and_reconciles_without_resend(self):
        pub, row = self.approved_change()
        original = self.mock.update_price
        def timeout(*args, **kwargs):
            original(*args, **kwargs)
            raise TimeoutError('secret-do-not-log')
        with patch.object(self.mock, 'update_price', side_effect=timeout):
            failed = self.execute(row)
        self.assertEqual('UNKNOWN', failed['execution_status'])
        self.assertEqual(1, failed['reconcile_required'])
        self.service = ApprovalService(self.factory, mode='MOCK')
        with self.assertRaises(ValueError):
            self.execute(row)
        with patch.object(self.service.provider, 'update_price', side_effect=AssertionError('Never resend')):
            done = self.service.reconcile(row['approval_request_id'], actor_id='Human')
        self.assertEqual('RECONCILED', done['execution_status'])
        self.assertEqual(1, done['attempt_count'])
        self.assertIn('ebay.execution.reconciled', {r['action'] for r in self.rows('audit_logs')})
        self.assertEqual(self.legacy, self.rows('listings'))

    def test_actual_projection_transaction_failure_rolls_back_then_reconciles(self):
        pub, row = self.approved_change()
        before = self.rows('marketplace_listings')
        with self.factory() as c:
            c.execute("CREATE TRIGGER fail_projection BEFORE UPDATE ON marketplace_listings BEGIN SELECT RAISE(ABORT,'disk failure'); END")
        failed = self.execute(row)
        self.assertEqual('UNKNOWN', failed['execution_status'])
        self.assertEqual(before, self.rows('marketplace_listings'))
        self.assertEqual(35, self.mock.get_listing(pub['external_listing_id'])['payload']['price'])
        with self.factory() as c:
            c.execute('DROP TRIGGER fail_projection')
        self.assertEqual('RECONCILED', self.service.reconcile(row['approval_request_id'], actor_id='Human')['execution_status'])

    def test_unknown_without_receipt_does_not_retry_even_when_values_match(self):
        pub, row = self.approved_change()
        with patch.object(self.mock, 'update_price', side_effect=TimeoutError()):
            self.execute(row)
        self.remote_edit(pub, {'price':35})
        with self.assertRaises(ValueError):
            self.service.reconcile(row['approval_request_id'], actor_id='Human')
        with self.assertRaises(ValueError):
            self.execute(row)
        self.assertEqual(1, len(self.rows('ebay_mock_receipts')))

    def test_reconcile_detects_later_external_change_and_keeps_unknown(self):
        pub, row = self.approved_change()
        with patch.object(self.service, '_finish', side_effect=RuntimeError('projection')):
            self.execute(row)
        self.remote_edit(pub, {'price':50})
        with self.assertRaises(PublicationError):
            self.service.reconcile(row['approval_request_id'], actor_id='Human')
        self.assertEqual(1, self.service.get(row['approval_request_id'])['reconcile_required'])
        self.assertEqual(30, json.loads(self.rows('marketplace_listings')[0]['current_payload_json'])['price'])

    def test_reconciliation_read_errors_are_redacted_and_never_resend(self):
        pub, row = self.approved_change()
        with patch.object(self.service, '_finish', side_effect=RuntimeError('projection')):
            self.execute(row)
        for method in ('lookup_execution', 'get_listing'):
            with self.subTest(method=method), patch.object(self.mock, method, side_effect=TimeoutError('secret-token')), \
                    patch.object(self.mock, 'update_price') as send:
                with self.assertRaises(PublicationError) as caught:
                    self.service.reconcile(row['approval_request_id'], actor_id='Human')
                self.assertNotIn('secret-token', str(caught.exception))
                self.assertTrue(caught.exception.uncertain)
                send.assert_not_called()
        self.assertEqual(1, self.service.get(row['approval_request_id'])['reconcile_required'])
        self.assertEqual('RECONCILED', self.service.reconcile(row['approval_request_id'], actor_id='Human')['execution_status'])

    def test_partial_or_wrong_result_cannot_project_success(self):
        pub, row = self.approved_change('REVISE_LISTING', {'price':35, 'quantity':0})
        partial = self.mock.get_listing(pub['external_listing_id'])
        partial['payload']['price'] = 35
        partial['version'] += 1
        with patch.object(self.mock, 'revise_listing', return_value=partial):
            failed = self.execute(row)
        self.assertEqual('UNKNOWN', failed['execution_status'])
        self.assertEqual(30, json.loads(self.rows('marketplace_listings')[0]['current_payload_json'])['price'])
        self.assertEqual(1, len(self.rows('ebay_mock_receipts')))

    def test_valid_looking_response_without_remote_change_is_unknown(self):
        pub, row = self.approved_change()
        fake = self.mock.get_listing(pub['external_listing_id'])
        fake['payload']['price'] = 35
        fake['version'] += 1
        with patch.object(self.mock, 'update_price', return_value=fake):
            failed = self.execute(row)
        self.assertEqual('UNKNOWN', failed['execution_status'])
        self.assertEqual(1, failed['reconcile_required'])

    def test_dry_run_change_validates_but_never_updates_mock(self):
        pub = self.publish()
        before = self.rows('marketplace_listings'), self.rows('ebay_mock_listings')
        self.service = ApprovalService(self.factory, mode='DRY_RUN')
        row = self.approve(self.change(pub, 'UPDATE_QUANTITY', {'quantity':0}))
        with patch.object(self.service.provider, 'update_quantity', side_effect=AssertionError('No writes')):
            done = self.execute(row)
        self.assertEqual('DRY_RUN', done['execution_status'])
        self.assertEqual(before, (self.rows('marketplace_listings'), self.rows('ebay_mock_listings')))

    def test_unapproved_and_end_double_confirmation(self):
        pub = self.publish()
        row = self.change(pub, 'END_LISTING', {})
        with self.assertRaises(ValueError):
            self.execute(row)
        with self.assertRaises(ValueError):
            self.approve(row)
        approved = self.approve(row, end_confirmed=True)
        self.assertTrue(json.loads(approved['approved_payload_json'])['end_confirmed'])
        self.assertEqual('SUCCEEDED', self.execute(row)['status'])
        with self.assertRaises(ValueError):
            self.change(pub, 'UPDATE_QUANTITY', {'quantity':1}, 'after-end')


class ListingChangeLibSQLTests(ListingChangeTests):
    driver = 'libsql'


class ListingChangeTursoConfiguredTests(ListingChangeTests):
    driver = 'libsql'

    def setUp(self):
        super().setUp()
        config = patch.dict(os.environ, {'TURSO_DATABASE_URL':'libsql://stage7-test.invalid', 'TURSO_AUTH_TOKEN':'unused'})
        config.start()
        self.addCleanup(config.stop)
