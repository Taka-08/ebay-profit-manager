import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from app_database import ClosingSQLiteConnection, RemoteCompatibleConnection
from integrated_ebay.draft_service import ListingDraftService
from integrated_ebay.migrations import MIGRATIONS, run_schema_migrations, utc_now
from integrated_ebay.publication_provider import MockPublicationProvider, PublicationError, publication_provider
from integrated_ebay.publication_service import PublicationService
from integrated_ebay.services import ProductCatalogService


def expected_values(data):
    # Test double; production receives the unchanged manager calculation function.
    revenue = (data['listing_price_usd'] + data['buyer_shipping_usd']) * data['exchange_rate']
    profit = revenue - data['purchase_price_yen'] - data['international_shipping_yen']
    return dict(profit_yen=profit, expected_profit_yen=profit, profit_margin=profit / revenue * 100,
                gross_sales_yen=revenue)


class PublicationTests(unittest.TestCase):
    driver = 'sqlite'

    def factory(self):
        if self.driver == 'libsql':
            import libsql
            c = RemoteCompatibleConnection(libsql.connect(str(self.path)))
        else:
            c = sqlite3.connect(self.path, factory=ClosingSQLiteConnection, timeout=15)
            c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        return c

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='publication-')
        self.path = Path(self.temp.name) / 'local.sqlite3'
        self.remote = patch('integrated_ebay.publication_service.remote_database_is_configured', return_value=False)
        self.remote.start()
        with self.factory() as c:
            c.execute('''CREATE TABLE listings(id INTEGER PRIMARY KEY, product_name TEXT, platform TEXT,
              listing_date TEXT, listing_price_usd REAL, listing_price REAL, currency_code TEXT,
              purchase_price_yen REAL, international_shipping_yen REAL, exchange_rate REAL, status TEXT,
              shipping_breakdown_json TEXT NOT NULL DEFAULT '', product_url TEXT, sku TEXT, expected_profit_yen REAL,
              profit_yen REAL, profit_margin REAL, platform_memo TEXT, created_at TEXT, updated_at TEXT)''')
            for i in range(94):
                c.execute('INSERT INTO listings(id,product_name,shipping_breakdown_json) VALUES (?,?,?)',
                          (i+1, f'Legacy {i}', ' {"old": ' + str(i) + '} '))
            c.execute('CREATE TABLE schema_migrations(migration_id TEXT PRIMARY KEY, description TEXT, applied_at TEXT)')
            for migration in MIGRATIONS[:3]:
                migration.apply(c)
                c.execute('INSERT INTO schema_migrations VALUES (?,?,?)', (migration.migration_id, migration.description, utc_now()))
        # Local fixture backup before the additive migration; never connects to Turso.
        with sqlite3.connect(self.path, factory=ClosingSQLiteConnection) as source, sqlite3.connect(Path(self.temp.name) / 'before.sqlite3', factory=ClosingSQLiteConnection) as dest:
            source.backup(dest)
        self.legacy = self.rows('listings')
        self.assertEqual(('0004_listing_publications',), run_schema_migrations(self.factory))
        self.catalog = ProductCatalogService(self.factory)
        self.pid = self.catalog.create_product(dict(product_name='Camera', sku='CAM-1', platform='eBay',
            category='Cameras', country_of_origin='JP', purchase_price=1000, purchase_currency='JPY',
            weight_g=500, length_cm=20, width_cm=10, height_cm=5))
        self.catalog.update_inventory(self.pid, dict(stock_mode='IN_STOCK', on_hand_quantity=3, reserved_quantity=0))
        self.drafts = ListingDraftService(self.factory)
        self.provider = MockPublicationProvider()
        self.publisher = PublicationService(self.factory, calculate_expected=expected_values,
                                             provider=self.provider, allow_mock=True)
        self.did = self.drafts.create(self.pid, actor_id='Author', price=30)
        self.drafts.generate(self.did, expected_revision=1, actor_id='Author')
        self.inputs = dict(exchange_rate=150, shipping_yen=500, shipping_carrier='Japan Post',
                           shipping_service='EMS', required_specifics=['Brand'], specifics_reviewed=True)
        self.edit(title='Example Camera', condition_name='Used', condition_id='3000', category_id='31388',
                  item_specifics_json='{"Brand":{"value":"Example","needs_review":false}}',
                  shipping_profile_json='{"shipping_breakdown_json":" {\\"total_shipping_yen\\":500} "}',
                  publication_input_json=json.dumps(self.inputs))

    def tearDown(self):
        self.remote.stop()
        self.temp.cleanup()

    def rows(self, table):
        with self.factory() as c:
            return [dict(r) for r in c.execute('SELECT * FROM ' + table)]

    def edit(self, **values):
        return self.drafts.update(self.did, values, expected_revision=self.drafts.get(self.did)['revision'], actor_id='Editor')

    def transition(self, state):
        return self.drafts.transition(self.did, state, expected_revision=self.drafts.get(self.did)['revision'],
                                       actor_id='Approver', reviewed=True)

    def approve(self):
        self.transition('READY_FOR_REVIEW')
        return self.transition('APPROVED')

    def test_migration_idempotent_and_94_snapshots_unchanged(self):
        self.assertEqual((), run_schema_migrations(self.factory))
        self.assertEqual(self.legacy, self.rows('listings'))
        self.assertTrue(all(r['product_id'] is None for r in self.rows('listings')))

    def test_approval_does_not_publish_or_outbox(self):
        with patch.object(self.provider, 'publish') as send:
            self.approve()
            send.assert_not_called()
        self.assertEqual('APPROVED', self.publisher.get(self.did)['status'])
        self.assertEqual([], self.rows('outbox_events'))
        self.assertEqual(94, len(self.rows('listings')))

    def test_publish_item_id_registration_snapshot_and_audit(self):
        self.approve()
        result = self.publisher.publish(self.did, actor_id='Publisher')
        self.assertEqual('PUBLISHED', result['status'])
        self.assertTrue(result['ebay_item_id'].startswith('MOCK-'))
        row = self.rows('listings')[-1]
        self.assertEqual(self.pid, row['product_id'])
        self.assertEqual(' {"total_shipping_yen":500} ', row['shipping_breakdown_json'])
        self.assertEqual(3000, row['profit_yen'])
        self.assertEqual(30, result['final_price'])
        self.assertEqual(3, result['quantity'])
        self.assertIsNotNone(result['published_at'])
        self.assertEqual(self.legacy, self.rows('listings')[:94])
        actions = {r['action'] for r in self.rows('audit_logs')}
        self.assertTrue({'listing_draft.ai_generated','listing_draft.updated','listing_draft.approved',
                         'publication.started','publication.succeeded','listing.registered'} <= actions)

    def test_missing_fields_block_approval_and_provider(self):
        for values in ({'title': ''}, {'category_id': None}, {'condition_id': None}, {'price': 0},
                       {'quantity': 0}, {'item_specifics_json': '{}'}):
            with self.subTest(values=values):
                old = self.drafts.get(self.did)
                self.edit(**values)
                self.transition('READY_FOR_REVIEW')
                with self.assertRaises(ValueError):
                    self.transition('APPROVED')
                self.assertIsNone(self.publisher.get(self.did))
                self.edit(**{k: old[k] for k in values})
        for key, value in (('weight_g', 0), ('length_cm', -1), ('country_of_origin', ''),
                           ('sku', ''), ('specifics_reviewed', False), ('shipping_yen', 501)):
            self.edit(publication_input_json=json.dumps(dict(self.inputs, **{key: value})))
            self.transition('READY_FOR_REVIEW')
            with self.assertRaises(ValueError):
                self.transition('APPROVED')

    def test_unapproved_and_stale_approval_rejected(self):
        with self.assertRaises(ValueError):
            self.publisher.publish(self.did, actor_id='Publisher')
        self.approve()
        with self.assertRaises(ValueError):
            self.transition('APPROVED')
        self.assertEqual(1, len(self.rows('listing_publications')))

    def test_reject_edit_and_reapprove(self):
        self.approve()
        self.transition('REJECTED')
        self.assertIsNone(self.publisher.get(self.did))
        self.edit(title='Edited Camera')
        self.approve()
        self.assertEqual(2, len(self.rows('listing_publications')))

    def test_duplicate_publication_calls_do_not_duplicate_registration(self):
        self.approve()
        with patch.object(self.provider, 'publish', wraps=self.provider.publish) as call:
            a = self.publisher.publish(self.did, actor_id='Publisher')
            b = self.publisher.publish(self.did, actor_id='Publisher')
            self.assertEqual(a, b)
            self.assertEqual(1, call.call_count)
        self.assertEqual(95, len(self.rows('listings')))

    def test_simultaneous_publish_claim(self):
        self.approve()
        def run():
            try:
                return self.publisher.publish(self.did, actor_id='Publisher')['status']
            except ValueError:
                return 'IN_PROGRESS'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        self.assertIn('PUBLISHED', results)
        self.assertEqual(95, len(self.rows('listings')))
        self.assertEqual(1, self.publisher.get(self.did)['attempt_count'])

    def test_failure_preserves_draft_and_retry(self):
        self.approve()
        before = self.drafts.get(self.did)
        with patch.object(self.provider, 'publish', side_effect=PublicationError('MOCK_FAILURE', 'Mock failure')):
            result = self.publisher.publish(self.did, actor_id='Publisher')
        self.assertEqual('FAILED', result['status'])
        self.assertEqual(before, self.drafts.get(self.did))
        self.assertIsNotNone(result['failed_at'])
        self.assertEqual(94, len(self.rows('listings')))
        result = self.publisher.publish(self.did, actor_id='Publisher')
        self.assertEqual(('PUBLISHED', 2), (result['status'], result['attempt_count']))

    def test_unknown_outcome_does_not_resend_and_reconciles(self):
        self.approve()
        with patch.object(self.provider, 'publish', side_effect=TimeoutError('private secret')):
            result = self.publisher.publish(self.did, actor_id='Publisher')
        self.assertNotIn('secret', result['error_message'])
        with patch.object(self.provider, 'publish', side_effect=AssertionError('resend')):
            with self.assertRaises(ValueError):
                self.publisher.publish(self.did, actor_id='Publisher')
            result = self.publisher.reconcile(self.did, actor_id='Publisher')
        self.assertEqual('PUBLISHED', result['status'])

    def test_local_persistence_failure_rolls_back_and_reconciles(self):
        self.approve()
        with patch('integrated_ebay.publication_service.ListingRegistrationService.register', side_effect=RuntimeError('DB failure')):
            with self.assertRaises(RuntimeError):
                self.publisher.publish(self.did, actor_id='Publisher')
        self.assertEqual('PUBLISHING', self.publisher.get(self.did)['status'])
        self.assertEqual(94, len(self.rows('listings')))
        result = self.publisher.reconcile(self.did, actor_id='Publisher')
        self.assertEqual('PUBLISHED', result['status'])

    def test_audit_failure_rolls_back_registration(self):
        self.approve()
        original = self.publisher._audit
        def audit(c, record, action, actor, after):
            if action == 'succeeded':
                raise RuntimeError('audit failure')
            return original(c, record, action, actor, after)
        with patch.object(self.publisher, '_audit', side_effect=audit):
            with self.assertRaises(RuntimeError):
                self.publisher.publish(self.did, actor_id='Publisher')
        self.assertEqual(94, len(self.rows('listings')))
        self.publisher.reconcile(self.did, actor_id='Publisher')
        self.assertEqual(95, len(self.rows('listings')))

    def test_published_draft_cannot_edit_generate_reject(self):
        self.approve()
        self.publisher.publish(self.did, actor_id='Publisher')
        for action in (lambda: self.edit(title='Oops'), lambda: self.transition('REJECTED'),
                       lambda: self.drafts.generate(self.did, expected_revision=self.drafts.get(self.did)['revision'], actor_id='AI')):
            with self.assertRaises(ValueError):
                action()

    def test_duplicate_product_draft_and_sku_blocked(self):
        self.approve()
        other = self.drafts.create(self.pid, actor_id='Other', price=30)
        original = self.drafts.get(self.did)
        from integrated_ebay.draft_service import EDIT_FIELDS
        self.drafts.update(other, {k: original[k] for k in EDIT_FIELDS}, actor_id='Other', expected_revision=1)
        self.drafts.transition(other, 'READY_FOR_REVIEW', actor_id='Other', expected_revision=2)
        with self.assertRaises(ValueError):
            self.drafts.transition(other, 'APPROVED', actor_id='Other', expected_revision=3, reviewed=True)

    def test_sku_product_collision(self):
        self.catalog.create_product(dict(product_name='Other', sku='cam-1'))
        with self.assertRaises(ValueError):
            self.approve()

    def test_inventory_checked_again_at_publish(self):
        self.approve()
        self.catalog.update_inventory(self.pid, dict(stock_mode='IN_STOCK', on_hand_quantity=0, reserved_quantity=0))
        with self.assertRaises(ValueError):
            self.publisher.publish(self.did, actor_id='Publisher')
        self.assertEqual(0, self.publisher.get(self.did)['attempt_count'])

    def test_live_sandbox_disabled_and_remote_mock_blocked(self):
        for mode in ('LIVE', 'SANDBOX', 'DISABLED'):
            with self.assertRaises(ValueError):
                publication_provider(mode)
        self.approve()
        with patch('integrated_ebay.publication_service.remote_database_is_configured', return_value=True):
            with self.assertRaises(ValueError):
                self.publisher.publish(self.did, actor_id='Publisher')
        self.assertEqual(94, len(self.rows('listings')))

    def test_no_network_needed(self):
        with patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')):
            self.approve()
            self.publisher.publish(self.did, actor_id='Publisher')

    def test_missing_shipping_snapshot_keeps_legacy_empty_string(self):
        self.edit(shipping_profile_json='{}')
        self.approve()
        self.publisher.publish(self.did, actor_id='Publisher')
        self.assertEqual('', self.rows('listings')[-1]['shipping_breakdown_json'])

    def test_provider_payload_does_not_include_private_costs_or_sources(self):
        self.edit(publication_input_json=json.dumps(dict(self.inputs, source_url='https://example.com/private-source')))
        self.approve()
        with patch.object(self.provider, 'publish', wraps=self.provider.publish) as send:
            self.publisher.publish(self.did, actor_id='Publisher')
        payload = send.call_args.args[0]
        for key in ('generation_input_json', 'source_url', 'purchase_price', 'approved_by'):
            self.assertNotIn(key, payload)
        self.assertNotIn('private-source', json.dumps(payload))

    def test_legacy_stage4_approval_is_not_automatically_publishable(self):
        with self.factory() as c:
            c.execute("UPDATE listing_drafts SET status='APPROVED' WHERE listing_draft_id=?", (self.did,))
        with self.assertRaises(ValueError):
            self.publisher.publish(self.did, actor_id='Publisher')


class LocalLibsqlPublicationTests(PublicationTests):
    driver = 'libsql'
