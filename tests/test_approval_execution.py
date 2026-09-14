import json
import os
import unittest
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import test_listing_publications as fixtures
from integrated_ebay.approval_migration import initialize_approval_storage
from integrated_ebay.approval_service import ApprovalService
from integrated_ebay.ebay_api import MockEbayProvider, OAuthClient, OAuthSettings, SandboxEbayProvider, ProductionEbayProvider
from integrated_ebay.publication_provider import PublicationError


class ApprovalExecutionTests(unittest.TestCase):
    driver = 'sqlite'
    factory = fixtures.PublicationTests.factory
    tearDown = fixtures.PublicationTests.tearDown
    rows = fixtures.PublicationTests.rows
    edit = fixtures.PublicationTests.edit
    transition = fixtures.PublicationTests.transition

    def setUp(self):
        fixtures.PublicationTests.setUp(self)
        self.assertEqual(('0005_approval_execution',), initialize_approval_storage(self.factory))
        self.transition('READY_FOR_REVIEW')
        self.transition('APPROVED')
        self.mock = MockEbayProvider(self.factory)
        self.service = ApprovalService(self.factory, calculate_expected=fixtures.expected_values,
                                       provider=self.mock, mode='MOCK')

    def proposal(self, key='create-test'):
        return self.service.propose_create(self.did, actor_id='AI planner', actor_type='ai', idempotency_key=key)

    def approve(self, r, **kwargs):
        return self.service.approve(r['approval_request_id'], expected_version=r['version'],
                                    actor_id='Human', reviewed=True, **kwargs)

    def execute(self, r):
        return self.service.execute(r['approval_request_id'], actor_id='Local executor')

    def publish(self):
        result = self.execute(self.approve(self.proposal()))
        self.assertEqual('SUCCEEDED', result['status'], result)
        return result

    def change(self, pub, action, changes, key='change'):
        return self.service.propose_change(pub['marketplace_listing_id'], action, changes,
            reason='Human supplied reason', source_status='Not monitored', actor_id='Planner',
            actor_type='ai', idempotency_key=key)

    def test_pending_and_rejected_never_execute(self):
        r = self.proposal()
        with self.assertRaises(ValueError):
            self.execute(r)
        self.assertFalse(self.rows('outbox_events'))
        self.service.reject(r['approval_request_id'], expected_version=r['version'], actor_id='Human')
        with self.assertRaises(ValueError):
            self.execute(r)
        self.assertFalse(self.rows('ebay_mock_listings'))

    def test_migration_and_all_legacy_bytes_unchanged(self):
        with patch('app_database.remote_database_is_configured', return_value=False):
            self.assertEqual((), initialize_approval_storage(self.factory))
        self.publish()
        self.assertEqual(self.legacy, self.rows('listings'))
        self.assertTrue(all(r['product_id'] is None for r in self.rows('listings')[:94]))
        self.assertEqual(1, sum(r['migration_id']=='0005_approval_execution' for r in self.rows('schema_migrations')))

    def test_publish_links_receipt_listing_product_and_snapshot(self):
        r = self.publish()
        mapping = self.rows('marketplace_listings')[0]
        self.assertEqual(self.pid, mapping['product_id'])
        self.assertEqual(self.did, mapping['listing_draft_id'])
        self.assertEqual(r['approval_request_id'], mapping['approval_request_id'])
        self.assertEqual(mapping['external_listing_id'], r['external_listing_id'])
        self.assertTrue(r['external_listing_id'].startswith('MOCK-'))
        self.assertTrue(mapping['published_at'])
        self.assertEqual(self.legacy, self.rows('listings'))
        self.assertIsNone(mapping['listing_id'])
        self.assertEqual('APPROVED', self.rows('listing_publications')[0]['status'])
        self.assertEqual('processed', self.rows('outbox_events')[0]['status'])

    def test_double_approve_execute_and_persistent_provider(self):
        r = self.proposal()
        self.assertEqual(r['approval_request_id'], self.proposal()['approval_request_id'])
        self.approve(r)
        self.approve(r)
        self.assertEqual(1, len(self.rows('outbox_events')))
        first = self.execute(r)
        self.assertEqual(first, self.execute(r))
        self.assertEqual(1, len(self.rows('ebay_mock_listings')))
        self.assertEqual(1, len(self.rows('approval_execution_attempts')))
        restarted = MockEbayProvider(self.factory)
        self.assertEqual(first['external_listing_id'], restarted.get_listing(first['external_listing_id'])['external_listing_id'])

    def test_concurrent_approval_and_execution(self):
        r = self.proposal()
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(lambda _: self.approve(r), range(2)))
        def attempt(_):
            try:
                return self.execute(r)['status']
            except ValueError:
                return 'BUSY'
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(attempt, range(2)))
        self.assertIn('SUCCEEDED', results)
        self.assertEqual(1, len(self.rows('outbox_events')))
        self.assertEqual(1, len(self.rows('ebay_mock_listings')))

    def test_price_quantity_revise_end_are_separate_and_once(self):
        pub = self.publish()
        legacy = self.rows('listings')
        cases = [('UPDATE_PRICE', {'price':215}), ('UPDATE_QUANTITY', {'quantity':0}),
                 ('REVISE_LISTING', {'title':'Revised camera'}), ('END_LISTING', {})]
        for n, (action, changes) in enumerate(cases):
            r = self.change(pub, action, changes, str(n))
            if action == 'END_LISTING':
                with self.assertRaises(ValueError):
                    self.approve(r)
            self.approve(r, end_confirmed=action=='END_LISTING')
            result = self.execute(r)
            self.assertEqual('SUCCEEDED', result['status'], result)
            self.execute(r)
            state = self.mock.get_listing(pub['external_listing_id'])
            self.assertEqual(n+2, state['version'])
            self.assertEqual('ENDED' if action=='END_LISTING' else 'ACTIVE', state['status'])
        self.assertEqual(legacy, self.rows('listings'))
        self.assertEqual(5, len(self.rows('ebay_mock_receipts')))

    def test_human_edit_and_immutable_approved_payload(self):
        pub = self.publish()
        r = self.change(pub, 'UPDATE_PRICE', {'price':215})
        edited = self.service.edit(r['approval_request_id'], {'price':220}, reason='Corrected cost',
                                   expected_version=r['version'], actor_id='Human')
        approved = self.approve(edited)
        with self.assertRaises(ValueError):
            self.service.edit(r['approval_request_id'], {'price':1}, reason='bad', expected_version=approved['version'], actor_id='Human')
        self.execute(r)
        saved = self.service.get(r['approval_request_id'])
        self.assertEqual(approved['approved_payload_json'], saved['approved_payload_json'])
        self.assertEqual(220, self.mock.get_listing(pub['external_listing_id'])['payload']['price'])

    def test_changed_draft_does_not_rewrite_approval(self):
        approved = self.approve(self.proposal())
        self.edit(title='A later unapproved title')
        failed = self.execute(approved)
        self.assertEqual('FAILED', failed['status'])
        self.assertEqual(approved['approved_payload_json'], failed['approved_payload_json'])
        self.assertEqual('APPROVAL_MISMATCH', failed['error_code'])
        self.assertIn('承認済みpayloadと現在の下書きが一致しません', failed['error_message'])
        self.assertEqual(0, failed['reconcile_required'])
        cancelled = self.service.cancel(failed['approval_request_id'], expected_version=failed['version'], actor_id='Human')
        self.assertEqual('CANCELLED', cancelled['status'])
        self.assertFalse(self.rows('ebay_mock_listings'))
        self.transition('READY_FOR_REVIEW')
        self.transition('APPROVED')
        fresh = self.approve(self.proposal('re-proposed'))
        result = self.execute(fresh)
        self.assertEqual('SUCCEEDED', result['status'], result)
        self.assertNotEqual(approved['approved_payload_json'], fresh['approved_payload_json'])
        self.assertEqual(approved['approved_payload_json'], self.service.get(approved['approval_request_id'])['approved_payload_json'])
        self.assertEqual(1, len(self.rows('ebay_mock_listings')))
        self.assertEqual(self.legacy, self.rows('listings')[:94])

    def test_legacy_publish_cannot_bypass_queue(self):
        with self.assertRaises(ValueError):
            self.publisher.publish(self.did, actor_id='Legacy')
        r = self.proposal()
        with self.assertRaises(ValueError):
            self.publisher.publish(self.did, actor_id='Legacy')
        self.approve(r)
        with self.assertRaises(ValueError):
            self.publisher.publish(self.did, actor_id='Legacy')

    def test_known_failure_and_retry(self):
        r = self.approve(self.proposal())
        with patch.object(self.mock, 'create_listing', side_effect=PublicationError('TEST_FAILURE','test')):
            failed = self.execute(r)
        self.assertEqual('FAILED', failed['status'])
        self.assertEqual(0, failed['reconcile_required'])
        self.assertEqual(r['approved_payload_json'], failed['approved_payload_json'])
        succeeded = self.execute(r)
        self.assertEqual('SUCCEEDED', succeeded['status'], succeeded)
        self.assertEqual(2, succeeded['attempt_count'])
        self.assertEqual(['FAILED','SUCCEEDED'], [h['status'] for h in self.service.history(r['approval_request_id'])])
        self.assertEqual(94, len(self.rows('listings')))

    def test_uncertain_result_reconciles_without_resend(self):
        pub = self.publish()
        r = self.approve(self.change(pub, 'UPDATE_PRICE', {'price':35}))
        original = self.mock.update_price
        def timeout_after_write(*args, **kwargs):
            original(*args, **kwargs)
            raise PublicationError('UNKNOWN_RESULT','timeout',uncertain=True)
        with patch.object(self.mock, 'update_price', side_effect=timeout_after_write):
            failed = self.execute(r)
        self.assertEqual(1, failed['reconcile_required'])
        with self.assertRaises(ValueError):
            self.execute(r)
        result = self.service.reconcile(r['approval_request_id'], actor_id='Human')
        self.assertEqual('SUCCEEDED', result['status'])
        self.assertEqual(2, self.mock.get_listing(pub['external_listing_id'])['version'])
        self.assertEqual(2, len(self.rows('ebay_mock_receipts')))

    def test_result_projection_failure_and_create_recovery(self):
        r = self.approve(self.proposal())
        with patch.object(self.service, '_finish', side_effect=RuntimeError('disk transient')):
            failed = self.execute(r)
        self.assertEqual(1, failed['reconcile_required'])
        self.assertEqual(94, len(self.rows('listings')))
        result = self.service.reconcile(r['approval_request_id'], actor_id='Human')
        self.assertEqual('SUCCEEDED', result['status'])
        self.assertEqual(1, len(self.rows('marketplace_listings')))
        self.assertEqual(94, len(self.rows('listings')))

    def test_no_receipt_never_blindly_retries(self):
        pub = self.publish()
        r = self.approve(self.change(pub, 'UPDATE_PRICE', {'price':35}))
        with patch.object(self.mock, 'update_price', side_effect=RuntimeError('secret-token-do-not-log')):
            failed = self.execute(r)
        self.assertEqual('FAILED', failed['status'])
        with self.assertRaises(ValueError):
            self.service.reconcile(r['approval_request_id'], actor_id='Human')
        self.assertNotIn('secret-token', json.dumps(self.rows('audit_logs') + self.rows('approval_requests')))

    def test_stale_update_cannot_overwrite_newer_change(self):
        pub = self.publish()
        a = self.approve(self.change(pub, 'UPDATE_PRICE', {'price':35}, 'a'))
        b = self.approve(self.change(pub, 'UPDATE_PRICE', {'price':40}, 'b'))
        self.execute(a)
        failed = self.execute(b)
        self.assertEqual('FAILED', failed['status'])
        self.assertEqual('STALE', failed['error_code'])
        self.assertEqual(35, self.mock.get_listing(pub['external_listing_id'])['payload']['price'])

    def test_human_confirmation_mode_cancel_and_idempotency_conflict(self):
        r = self.proposal()
        with self.assertRaises(ValueError):
            self.service.approve(r['approval_request_id'], expected_version=1, actor_id='AI', actor_type='ai', reviewed=True)
        with self.assertRaises(ValueError):
            self.service.approve(r['approval_request_id'], expected_version=1, actor_id='Human')
        with self.assertRaises(ValueError):
            self.service.propose_create(self.did, actor_id='AI', idempotency_key='create-test', reason='different')
        a = self.approve(r)
        self.service.cancel(r['approval_request_id'], expected_version=a['version'], actor_id='Human')
        with self.assertRaises(ValueError):
            self.execute(r)

    def test_outbox_payload_tampering_blocks_execution(self):
        r = self.approve(self.proposal())
        with self.factory() as c:
            c.execute("UPDATE outbox_events SET payload_json='{}' WHERE event_id=?", (r['outbox_event_id'],))
        with self.assertRaises(ValueError):
            self.execute(r)
        self.assertFalse(self.rows('ebay_mock_listings'))

    def test_dry_run_has_no_mock_or_listing_side_effects(self):
        self.service = ApprovalService(self.factory, mode='DRY_RUN')
        r = self.execute(self.approve(self.proposal()))
        self.assertEqual('SUCCEEDED', r['status'])
        self.assertEqual('DRY_RUN', r['execution_status'])
        self.assertIsNone(r['external_listing_id'])
        self.assertFalse(self.rows('ebay_mock_listings'))
        self.assertEqual(self.legacy, self.rows('listings'))

    def test_required_audits_actor_types_and_explicit_worker(self):
        r = self.approve(self.proposal())
        result = self.service.execute_next(actor_id='Worker')
        self.assertEqual('SUCCEEDED', result['status'])
        self.assertIsNone(self.service.execute_next(actor_id='Worker'))
        actions = {r['action'] for r in self.rows('audit_logs')}
        self.assertTrue({'proposal.created','approval.approved','ebay.execution.queued','ebay.execution.started',
                         'ebay.execution.succeeded','listing.mock_published'} <= actions)
        actors = {r['actor_type'] for r in self.rows('audit_logs')}
        self.assertTrue({'human','ai','system'} <= actors)

    def test_disabled_external_modes_and_production_migration_guard(self):
        for cls in (SandboxEbayProvider, ProductionEbayProvider):
            provider = cls()
            for method in ('create_listing','revise_listing','update_price','update_quantity','end_listing'):
                with self.assertRaises(PublicationError):
                    getattr(provider, method)({}, idempotency_key='x')
        for mode in ('SANDBOX','PRODUCTION'):
            with self.assertRaises(PublicationError):
                ApprovalService(self.factory, mode=mode).propose_create(self.did, actor_id='Human', idempotency_key='no')
        with patch('app_database.remote_database_is_configured', return_value=True):
            with self.assertRaises(ValueError):
                initialize_approval_storage(self.factory)

    def test_mock_writes_only_stage6_tables_and_its_audit_outbox(self):
        allowed = {'approval_requests', 'approval_execution_attempts', 'marketplace_listings',
                   'ebay_mock_listings', 'ebay_mock_receipts', 'audit_logs', 'outbox_events'}
        with self.factory() as c:
            protected = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                         if r[0] not in allowed]
            # Reject even transient writes to existing application data.
            for table in protected:
                for operation in ('INSERT', 'UPDATE', 'DELETE'):
                    c.execute(f'''CREATE TRIGGER "protect_{table}_{operation}" BEFORE {operation} ON "{table}"
                        BEGIN SELECT RAISE(ABORT, 'protected existing table'); END''')
        before = {t: self.rows(t) for t in protected}
        pub = self.publish()
        for n, (action, changes) in enumerate((('UPDATE_PRICE', {'price':45}), ('UPDATE_QUANTITY', {'quantity':1}),
                ('REVISE_LISTING', {'title':'Mock only'}), ('END_LISTING', {}))):
            r = self.approve(self.change(pub, action, changes, f'protected-{n}'), end_confirmed=action=='END_LISTING')
            self.assertEqual('SUCCEEDED', self.execute(r)['status'])
        self.assertEqual(before, {t: self.rows(t) for t in protected})
        self.assertEqual(self.legacy, self.rows('listings'))
        self.assertTrue(all(r['product_id'] is None for r in self.rows('listings')))
        self.assertTrue(all(r['listing_id'] is None for r in self.rows('marketplace_listings')))
        self.assertTrue(all(r['entity_type']=='approval_request' for r in self.rows('audit_logs')
                            if r['action'].startswith(('proposal.', 'approval.', 'ebay.execution.', 'listing.mock_'))))
        with self.factory() as c:
            self.assertFalse(c.execute('PRAGMA foreign_key_check').fetchall())

    def test_mock_cannot_reach_real_api_oauth_or_legacy_registration(self):
        forbidden = ['socket.socket.connect', 'socket.create_connection', 'socket.getaddrinfo',
                     'requests.sessions.Session.request', 'urllib.request.urlopen', 'http.client.HTTPConnection.connect',
                     'integrated_ebay.ebay_api.OAuthSettings.load',
                     'integrated_ebay.ebay_api.OAuthClient.authorize',
                     'integrated_ebay.ebay_api.OAuthClient.refresh_access_token',
                     'integrated_ebay.publication_service.PublicationService.publish',
                     'integrated_ebay.publication_service.PublicationService.reconcile',
                     'integrated_ebay.services.ListingRegistrationService.register']
        for cls in ('SandboxEbayProvider', 'ProductionEbayProvider'):
            forbidden.extend('integrated_ebay.ebay_api.'+cls+'.'+method for method in
                ('create_listing','revise_listing','update_price','update_quantity','end_listing','lookup_execution','get_listing'))
        with ExitStack() as stack:
            calls = [stack.enter_context(patch(target, side_effect=AssertionError('Forbidden transport/registration'))) for target in forbidden]
            pub = self.publish()
            for n, (action, changes) in enumerate((('UPDATE_PRICE', {'price':40}), ('UPDATE_QUANTITY', {'quantity':2}),
                    ('REVISE_LISTING', {'title':'Transport-free'}), ('END_LISTING', {}))):
                r = self.approve(self.change(pub, action, changes, f'network-{n}'), end_confirmed=action=='END_LISTING')
                self.assertEqual('SUCCEEDED', self.execute(r)['status'])
            for call in calls:
                call.assert_not_called()

    def test_external_provider_or_subclass_cannot_enter_mock_service(self):
        class DisguisedProvider(MockEbayProvider):
            def create_listing(self, *args, **kwargs):
                raise AssertionError('Never dispatch')
        for provider in (ProductionEbayProvider(), SandboxEbayProvider(), DisguisedProvider(self.factory)):
            with self.assertRaises(ValueError):
                ApprovalService(self.factory, mode='MOCK', provider=provider).propose_create(
                    self.did, actor_id='Human', idempotency_key='blocked')
        self.assertFalse(self.rows('approval_requests'))

    def test_production_setting_blocks_approval_and_execution_even_with_mock_provider(self):
        r = self.approve(self.proposal())
        for mode in ('production', 'sandbox'):
            with patch.dict(os.environ, {'EBAY_EXECUTION_MODE':mode}):
                service = ApprovalService(self.factory, provider=self.mock)
                with self.assertRaises(PublicationError):
                    service.approve(r['approval_request_id'], expected_version=r['version'], actor_id='Human', reviewed=True)
                with self.assertRaises(PublicationError):
                    service.execute(r['approval_request_id'], actor_id='Human')
        self.assertFalse(self.rows('ebay_mock_receipts'))

    def test_create_receipt_recovery_preserves_later_draft_without_resend(self):
        r = self.approve(self.proposal())
        with patch.object(self.service, '_finish', side_effect=RuntimeError('projection failure')):
            self.execute(r)
        self.edit(title='Later draft')
        before = self.rows('listing_drafts')
        with patch.object(self.mock, 'create_listing', side_effect=AssertionError('Never resend')):
            recovered = self.service.reconcile(r['approval_request_id'], actor_id='Human')
        self.assertEqual('SUCCEEDED', recovered['status'])
        self.assertEqual(before, self.rows('listing_drafts'))
        self.assertEqual(1, len(self.rows('ebay_mock_receipts')))
        self.assertEqual(self.legacy, self.rows('listings'))

    def test_current_draft_revision_is_checked_even_if_frozen_payload_stays_identical(self):
        r = self.approve(self.proposal())
        with self.factory() as c:
            c.execute('UPDATE listing_drafts SET revision=revision+1 WHERE listing_draft_id=?', (self.did,))
        failed = self.execute(r)
        self.assertEqual('APPROVAL_MISMATCH', failed['error_code'])
        self.assertEqual(0, failed['reconcile_required'])
        self.assertFalse(self.rows('ebay_mock_receipts'))

    def test_oauth_never_exposes_or_uses_secrets(self):
        config = OAuthSettings('SANDBOX', client_secret='private-token', access_token='private-access')
        self.assertNotIn('private', repr(config))
        with self.assertRaises(PublicationError):
            OAuthClient(config).authorize()
        with self.assertRaises(PublicationError):
            OAuthClient(config).refresh_access_token()


class ApprovalLocalLibSQLTests(ApprovalExecutionTests):
    driver = 'libsql'


class ApprovalTursoConfiguredLibSQLTests(ApprovalExecutionTests):
    """Actual libSQL SQL engine + Turso configuration, but no remote DB/network."""
    driver = 'libsql'

    def setUp(self):
        super().setUp()
        config = patch.dict(os.environ, {'TURSO_DATABASE_URL':'libsql://stage6-test.invalid', 'TURSO_AUTH_TOKEN':'unused-test-only'})
        config.start()
        self.addCleanup(config.stop)
        import app_database
        self.assertTrue(app_database.remote_database_is_configured())
        self.remote.stop()
        self.remote = patch('integrated_ebay.publication_service.remote_database_is_configured', return_value=True)
        self.remote.start()
