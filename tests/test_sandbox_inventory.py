"""Fake HTTP contract tests, NOT successful live Sandbox verification."""

import copy
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.error import HTTPError

import test_listing_publications as fixtures
from integrated_ebay.approval_migration import initialize_approval_storage
from integrated_ebay.ebay_api import OAuthSettings, OAuthClient, ProductionEbayProvider
from integrated_ebay.publication_provider import PublicationError
from integrated_ebay.sandbox_http import SandboxHTTP, REQUIRED_SCOPES, sandbox_guard
from integrated_ebay.sandbox_inventory import SandboxInventoryProvider
from integrated_ebay.sandbox_migration import initialize_sandbox_storage
from integrated_ebay.sandbox_service import SandboxApprovalService

ENV = {'EBAY_EXECUTION_MODE': 'SANDBOX', 'EBAY_ENVIRONMENT': 'SANDBOX',
       'EBAY_ENABLE_SANDBOX_API': 'true', 'EBAY_ENABLE_PRODUCTION_WRITES': 'false',
       'EBAY_SANDBOX_SELLER_EIAS': 'fixture-seller', 'EBAY_SANDBOX_SELLER_USER_ID': 'testuser_fixture',
       'EBAY_SANDBOX_ALLOWED_OFFER_IDS': '1001'}


class FakeHTTP:
    def __init__(self):
        self.calls = []
        self.user, self.eias, self.oos = 'testuser_fixture', 'fixture-seller', True
        self.offer = dict(offerId='1001', sku='LISTING-SKU', marketplaceId='EBAY_US', format='FIXED_PRICE',
            listingDuration='GTC', status='PUBLISHED', availableQuantity=3,
            pricingSummary={'price': {'value': '30.00', 'currency': 'USD'}},
            listing={'listingId': '2001', 'listingStatus': 'ACTIVE'})
        self.inventory = {'sku': 'LISTING-SKU', 'availability': {'shipToLocationAvailability': {'quantity': 3}}}
        self.total = 1
        self.failure = None
        self.partial = False
        self.read_failure = False

    def request(self, method, path, *, token='', body=None, headers=None, write=False):
        self.calls.append((method, path, copy.deepcopy(body), write))
        if write and self.failure == 'before':
            raise TimeoutError('SECRET_RAW_REMOTE_ERROR')
        if path == '/ws/api.dll':
            if headers['X-EBAY-API-CALL-NAME'] == 'GetUser':
                return f'<GetUserResponse><Ack>Success</Ack><User><UserID>{self.user}</UserID><EIASToken>{self.eias}</EIASToken></User></GetUserResponse>'.encode()
            return f'<GetUserPreferencesResponse><Ack>Success</Ack><OutOfStockControlPreference>{str(self.oos).lower()}</OutOfStockControlPreference></GetUserPreferencesResponse>'.encode()
        if not write:
            if self.read_failure:
                raise TimeoutError('SECRET_RAW_READ_ERROR')
            if '/offer?' in path:
                return {'total': self.total, 'offers': [copy.deepcopy(self.offer)]}
            if '/inventory_item/' in path:
                return copy.deepcopy(self.inventory)
            return copy.deepcopy(self.offer)
        if path.endswith('/withdraw'):
            self.offer['status'] = 'UNPUBLISHED'
            self.offer['listing']['listingStatus'] = 'ENDED'
            result = {'listingId': '2001'}
        else:
            r = body['requests'][0]
            o = r['offers'][0]
            if 'price' in o:
                self.offer['pricingSummary']['price'] = o['price']
            if 'availableQuantity' in o:
                self.offer['availableQuantity'] = o['availableQuantity']
                if not self.partial:
                    self.inventory['availability']['shipToLocationAvailability']['quantity'] = r['shipToLocationAvailability']['quantity']
            result = {'responses': [{'sku': 'LISTING-SKU', 'offerId': '1001', 'statusCode': 500 if self.partial else 200}]}
        if self.failure == 'after':
            raise TimeoutError('SECRET_RAW_REMOTE_ERROR')
        return result

    @property
    def writes(self):
        return [c for c in self.calls if c[3]]


class SandboxTests(unittest.TestCase):
    driver = 'sqlite'
    factory = fixtures.PublicationTests.factory
    rows = fixtures.PublicationTests.rows
    edit = fixtures.PublicationTests.edit
    tearDown = fixtures.PublicationTests.tearDown

    def setUp(self):
        fixtures.PublicationTests.setUp(self)
        initialize_approval_storage(self.factory)
        self.assertEqual(('0006_sandbox_inventory',), initialize_sandbox_storage(self.factory))
        self.config = patch.dict(os.environ, ENV)
        self.config.start()
        self.addCleanup(self.config.stop)
        self.http = FakeHTTP()
        self.settings = OAuthSettings('SANDBOX', access_token='fixture-only-not-a-real-token', scopes=REQUIRED_SCOPES)
        self.provider = SandboxInventoryProvider(self.factory, http=self.http, settings=self.settings)
        self.service = SandboxApprovalService(self.factory, provider=self.provider)
        self.mid = self.service.bind_existing_test_offer(self.pid, offer_id='1001', item_id='2001', sku='LISTING-SKU',
            marketplace='EBAY_US', currency='USD', actor_id='Human', test_target_confirmed=True)

    def proposal(self, action='UPDATE_PRICE', changes=None, key='test'):
        return self.service.propose_change(self.mid, action, {'price': 31.0} if changes is None else changes,
            actor_id='Planner', reason='Sandbox only', idempotency_key=key)

    def approve(self, r, **kwargs):
        return self.service.approve(r['approval_request_id'], expected_version=r['version'], actor_id='Human', reviewed=True, **kwargs)

    def execute(self, r):
        return self.service.execute(r['approval_request_id'], actor_id='Executor')

    def test_price_end_to_end_and_projection(self):
        r = self.execute(self.approve(self.proposal()))
        self.assertEqual('SUCCEEDED', r['status'], r)
        self.assertEqual('2001', r['external_listing_id'])
        self.assertEqual(31, json.loads(self.rows('sandbox_marketplace_listings')[0]['current_payload_json'])['price'])
        self.assertEqual('PROJECTED', self.rows('sandbox_api_dispatches')[0]['state'])
        self.assertEqual(self.legacy, self.rows('listings'))
        self.assertFalse(self.rows('marketplace_listings'))
        self.assertEqual('CAM-1', self.rows('products')[0]['sku'])
        self.assertEqual(1, len(self.http.writes))
        self.assertEqual({'offerId': '1001', 'price': {'value': '31.0', 'currency': 'USD'}},
                         self.http.writes[0][2]['requests'][0]['offers'][0])

    def test_quantity_both_levels(self):
        r = self.execute(self.approve(self.proposal('UPDATE_QUANTITY', {'quantity': 2})))
        self.assertEqual('SUCCEEDED', r['status'], r)
        values = json.loads(r['result_json'])['payload']
        self.assertEqual((2, 2, 2), (values['quantity'], values['offer_quantity'], values['inventory_quantity']))
        self.assertEqual('30.00', self.http.offer['pricingSummary']['price']['value'])

    def test_zero_not_end(self):
        r = self.execute(self.approve(self.proposal('UPDATE_QUANTITY', {'quantity': 0})))
        self.assertEqual('SUCCEEDED', r['status'], r)
        self.assertEqual('ACTIVE', json.loads(r['result_json'])['status'])
        self.assertFalse(any(c[1].endswith('/withdraw') for c in self.http.calls))

    def test_zero_without_oos_stops_before_write(self):
        self.http.oos = False
        r = self.execute(self.approve(self.proposal('UPDATE_QUANTITY', {'quantity': 0})))
        self.assertEqual('FAILED', r['status'])
        self.assertEqual(0, r['reconcile_required'])
        self.assertFalse(self.http.writes)

    def test_end_requires_confirmation_and_is_separate(self):
        r = self.proposal('END_LISTING', {})
        with self.assertRaises(ValueError):
            self.approve(r)
        result = self.execute(self.approve(r, end_confirmed=True))
        self.assertEqual('SUCCEEDED', result['status'], result)
        self.assertEqual('ENDED', json.loads(result['result_json'])['status'])
        self.assertTrue(self.http.writes[0][1].endswith('/withdraw'))

    def test_pending_direct_adapter_and_rejected_never_write(self):
        r = self.proposal()
        with self.assertRaises(ValueError):
            self.execute(r)
        with self.assertRaises(PublicationError):
            self.provider.update_price(json.loads(r['proposed_payload_json']), idempotency_key='test')
        self.service.reject(r['approval_request_id'], expected_version=r['version'], actor_id='Human')
        with self.assertRaises(ValueError):
            self.execute(r)
        self.assertFalse(self.http.writes)

    def test_idempotent_approval_execute_and_restart(self):
        r = self.proposal()
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(lambda _: self.approve(r), range(2)))
        def attempt(_):
            try:
                return self.execute(r)
            except ValueError:
                return None
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(attempt, range(2)))
        self.service = SandboxApprovalService(self.factory, provider=SandboxInventoryProvider(self.factory, http=self.http, settings=self.settings))
        self.assertEqual('SUCCEEDED', self.execute(r)['status'])
        self.assertEqual(1, len(self.http.writes))
        self.assertEqual(1, len(self.rows('sandbox_approval_attempts')))

    def test_remote_identity_and_before_mismatches(self):
        for field, value in [('sku','wrong'), ('offerId','999'), ('marketplaceId','EBAY_GB'),
                             ('availableQuantity',2), ('format','AUCTION')]:
            with self.subTest(field=field):
                original = copy.deepcopy(self.http.offer)
                r = self.approve(self.proposal(key=field))
                self.http.offer[field] = value
                result = self.execute(r)
                self.assertEqual('FAILED', result['status'])
                self.assertFalse(self.http.writes)
                self.http.offer = original

    def test_item_currency_price_inventory_seller_conflicts(self):
        for field in ('item','currency','price','inventory','user','eias','multiple_offers','group'):
            with self.subTest(field=field):
                self.http = FakeHTTP()
                self.provider.http = self.http
                r = self.approve(self.proposal(key=field))
                if field=='item': self.http.offer['listing']['listingId']='999'
                elif field=='currency': self.http.offer['pricingSummary']['price']['currency']='GBP'
                elif field=='price': self.http.offer['pricingSummary']['price']['value']='30.50'
                elif field=='inventory': self.http.inventory['availability']['shipToLocationAvailability']['quantity']=2
                elif field=='user': self.http.user='wrong'
                elif field=='eias': self.http.eias='wrong'
                elif field=='multiple_offers': self.http.total=2
                else: self.http.inventory['groupIds']=['group']
                result = self.execute(r)
                self.assertEqual('FAILED', result['status'], result)
                self.assertFalse(self.http.writes)

    def test_master_sku_separate_but_frozen(self):
        r = self.approve(self.proposal())
        with self.factory() as c:
            c.execute('UPDATE products SET sku=? WHERE product_id=?', ('other-master', self.pid))
        self.assertEqual('STALE', self.execute(r)['error_code'])
        self.assertFalse(self.http.writes)

    def test_timeout_after_success_reconcile_no_resend(self):
        self.http.failure = 'after'
        r = self.execute(self.approve(self.proposal()))
        self.assertEqual('UNKNOWN', r['execution_status'])
        self.assertNotIn('SECRET', str(r))
        with self.assertRaises(ValueError):
            self.execute(r)
        result = self.service.reconcile(r['approval_request_id'], actor_id='Human')
        self.assertEqual('RECONCILED', result['execution_status'])
        self.assertEqual(1, len(self.http.writes))

    def test_timeout_before_remote_success_stays_unknown(self):
        self.http.failure = 'before'
        r = self.execute(self.approve(self.proposal()))
        with self.assertRaises((PublicationError, ValueError)):
            self.service.reconcile(r['approval_request_id'], actor_id='Human')
        with self.assertRaises(ValueError):
            self.execute(r)
        self.assertEqual('UNKNOWN', self.service.get(r['approval_request_id'])['execution_status'])
        self.assertEqual(1, len(self.http.writes))

    def test_partial_quantity_update_never_succeeds(self):
        self.http.partial = True
        r = self.execute(self.approve(self.proposal('UPDATE_QUANTITY', {'quantity': 0})))
        self.assertEqual('UNKNOWN', r['execution_status'])
        with self.assertRaises(PublicationError):
            self.service.reconcile(r['approval_request_id'], actor_id='Human')
        self.assertEqual(1, len(self.http.writes))

    def test_remote_success_db_failure_recovery(self):
        r = self.approve(self.proposal())
        with patch.object(self.service, '_save_sandbox_result', side_effect=ValueError('SECRET DB ERROR')):
            result = self.execute(r)
        self.assertEqual('UNKNOWN', result['execution_status'])
        restored = self.service.reconcile(r['approval_request_id'], actor_id='Human')
        self.assertEqual('SUCCEEDED', restored['status'])
        self.assertEqual(1, len(self.http.writes))

    def test_unknown_blocks_other_approved_request_same_item(self):
        first = self.approve(self.proposal(key='first'))
        other = self.approve(self.proposal(changes={'price':32}, key='second'))
        self.http.failure='after'
        self.execute(first)
        with self.assertRaises(ValueError):
            self.execute(other)
        self.assertEqual(1, len(self.http.writes))

    def test_cancel_edit_reapprove(self):
        r = self.proposal()
        self.service.cancel(r['approval_request_id'], expected_version=r['version'], actor_id='Human')
        other = self.proposal(key='next')
        other = self.service.edit(other['approval_request_id'], {'price':32}, reason='new', expected_version=other['version'], actor_id='Human')
        self.assertEqual('SUCCEEDED', self.execute(self.approve(other))['status'])

    def test_remote_conflict_cancel_refresh_reapprove(self):
        r=self.approve(self.proposal())
        self.http.offer['pricingSummary']['price']['value']='30.50'
        r=self.execute(r)
        self.assertEqual('FAILED',r['status'])
        self.assertFalse(self.http.writes)
        self.service.cancel(r['approval_request_id'],expected_version=r['version'],actor_id='Human')
        self.service.refresh_test_offer(self.mid,actor_id='Human',refresh_confirmed=True)
        result=self.execute(self.approve(self.proposal(key='after-refresh')))
        self.assertEqual('SUCCEEDED',result['status'],result)
        self.assertEqual(1,len(self.http.writes))

    def test_refresh_cannot_bypass_unknown_or_pending_approval(self):
        r=self.proposal()
        with self.assertRaises(ValueError):
            self.service.refresh_test_offer(self.mid,actor_id='Human',refresh_confirmed=True)
        self.http.failure='after'
        r=self.execute(self.approve(r))
        with self.assertRaises(ValueError):
            self.service.refresh_test_offer(self.mid,actor_id='Human',refresh_confirmed=True)
        self.assertEqual('UNKNOWN',self.service.get(r['approval_request_id'])['execution_status'])

    def test_wrong_actions_disabled(self):
        for action in ('CREATE_LISTING','REVISE_LISTING','DELETE'):
            with self.assertRaises(PublicationError):
                self.proposal(action, {})
        self.assertFalse(self.http.writes)

    def test_remote_db_and_production_always_disabled(self):
        with patch('integrated_ebay.sandbox_service.remote_database_is_configured', return_value=True):
            with self.assertRaises(PublicationError): self.proposal()
        for env in ({'EBAY_ENABLE_PRODUCTION_WRITES':'true'}, {'EBAY_ENVIRONMENT':'PRODUCTION'},
                    {'EBAY_EXECUTION_MODE':'MOCK'}, {'EBAY_ENABLE_SANDBOX_API':''}):
            with patch.dict(os.environ, env):
                with self.assertRaises(PublicationError): self.proposal()
        with patch.dict(os.environ, {'EBAY_EXECUTION_MODE':'PRODUCTION', 'EBAY_ENABLE_PRODUCTION_WRITES':'true'}):
            with self.assertRaises(PublicationError): ProductionEbayProvider().update_price({}, idempotency_key='p')
        self.assertFalse(self.http.writes)

    def test_missing_token_scopes_and_allowed_target(self):
        for settings in (OAuthSettings('SANDBOX'), OAuthSettings('SANDBOX', access_token='fixture', scopes=()),
                         OAuthSettings('PRODUCTION', access_token='fixture', scopes=REQUIRED_SCOPES)):
            self.provider._settings=settings
            with self.assertRaises(PublicationError): self.proposal()
        self.provider._settings=self.settings
        with patch.dict(os.environ, {'EBAY_SANDBOX_ALLOWED_OFFER_IDS':'999'}):
            r=self.execute(self.approve(self.proposal()))
            self.assertEqual('FAILED', r['status'])
        self.assertFalse(self.http.writes)

    def test_additive_migration_idempotent_and_protected_94(self):
        self.assertEqual((), initialize_sandbox_storage(self.factory))
        self.assertEqual(self.legacy, self.rows('listings'))
        self.assertTrue(all(r['product_id'] is None for r in self.rows('listings')))
        self.assertFalse(self.rows('marketplace_listings'))
        with patch('app_database.remote_database_is_configured', return_value=True):
            with self.assertRaises(ValueError): initialize_sandbox_storage(self.factory)

    def test_audit_outbox_and_attempts(self):
        r=self.execute(self.approve(self.proposal()))
        actions={x['action'] for x in self.rows('audit_logs')}
        self.assertTrue({'proposal.created','approval.approved','ebay.execution.started','ebay.execution.succeeded'} <= actions)
        self.assertEqual('processed', self.rows('outbox_events')[0]['status'])
        self.assertTrue(r['approved_at'] and r['executed_at'])


class SandboxLibSQLTests(SandboxTests):
    driver = 'libsql'


class SandboxUITests(unittest.TestCase):
    driver = 'sqlite'
    setUp = SandboxTests.setUp
    tearDown = fixtures.PublicationTests.tearDown
    factory = fixtures.PublicationTests.factory
    rows = fixtures.PublicationTests.rows
    edit = fixtures.PublicationTests.edit
    proposal = SandboxTests.proposal

    def app(self):
        from streamlit.testing.v1 import AppTest
        global UI_SERVICE
        UI_SERVICE = self.service
        code = '''
from unittest.mock import patch
import test_sandbox_inventory as fixtures
from integrated_ebay.approval_ui import render_approvals
with patch('integrated_ebay.sandbox_service.SandboxApprovalService', lambda factory: fixtures.UI_SERVICE):
    render_approvals(fixtures.UI_SERVICE.factory)
'''
        return AppTest.from_string(code).run(timeout=60)

    def test_sandbox_ui_approval_and_execution(self):
        r = self.proposal()
        app = self.app()
        self.assertFalse(app.exception)
        app.text_input(key='approval_actor').set_value('Human')
        next(w for w in app.checkbox if w.label=='提案内容を人間が確認しました').check().run(timeout=60)
        next(w for w in app.button if w.label=='提案を承認').click().run(timeout=60)
        self.assertEqual('APPROVED', self.service.get(r['approval_request_id'])['status'])
        self.assertTrue(next(w for w in app.button if w.label=='Sandbox実行').disabled)
        next(w for w in app.checkbox if w.label.startswith('Sandboxのテスト出品に')).check().run(timeout=60)
        next(w for w in app.button if w.label=='Sandbox実行').click().run(timeout=60)
        self.assertFalse(app.exception)
        self.assertEqual('SUCCEEDED', self.service.get(r['approval_request_id'])['status'])
        self.assertTrue(any('Sandbox実行' in w.value for w in app.success))
        self.assertTrue(any('Production書き込み無効' in w.value for w in app.info))

    def test_missing_config_ui_no_network(self):
        before = len(self.http.calls)
        with patch.dict(os.environ, {'EBAY_ENABLE_SANDBOX_API':''}):
            app = self.app()
        self.assertFalse(app.exception)
        self.assertTrue(any('Sandbox通信' in w.value for w in app.warning))
        self.assertEqual(before, len(self.http.calls))


class HTTPGuardTests(unittest.TestCase):
    def setUp(self):
        p=patch.dict(os.environ, ENV)
        p.start()
        self.addCleanup(p.stop)

    def test_no_arbitrary_host_route_or_trading_writes(self):
        h=SandboxHTTP()
        with patch('integrated_ebay.sandbox_http.build_opener') as opener:
            for method, path in [('PUT','/sell/inventory/v1/offer/1001'), ('POST','/sell/inventory/v1/offer/1001/publish'),
                                 ('GET','https://api.ebay.com/sell/inventory/v1/offer/1001')]:
                with self.assertRaises(PublicationError): h.request(method,path,write=True)
            with self.assertRaises(PublicationError): h.request('POST','/ws/api.dll',headers={'X-EBAY-API-CALL-NAME':'EndItem'})
            opener.assert_not_called()

    def test_http_errors_not_retried_or_leaked(self):
        for status in (401,403,429,500,503,302):
            with self.subTest(status=status), patch('integrated_ebay.sandbox_http.build_opener') as opener:
                opener.return_value.open.side_effect=HTTPError('https://api.sandbox.ebay.com',status,'SECRET',{},None)
                with self.assertRaises(PublicationError) as caught:
                    SandboxHTTP().request('POST','/sell/inventory/v1/bulk_update_price_quantity',body={},write=True)
                self.assertTrue(caught.exception.uncertain)
                self.assertNotIn('SECRET',str(caught.exception))
                self.assertEqual(1,opener.return_value.open.call_count)

    def test_network_disconnect_unknown_no_retry(self):
        with patch('integrated_ebay.sandbox_http.build_opener') as opener:
            opener.return_value.open.side_effect=TimeoutError('SECRET')
            with self.assertRaises(PublicationError) as caught:
                SandboxHTTP().request('POST','/sell/inventory/v1/bulk_update_price_quantity',body={},write=True)
            self.assertTrue(caught.exception.uncertain)
            self.assertEqual(1,opener.return_value.open.call_count)

    def test_refresh_only_sandbox_no_auto_persistence(self):
        settings=OAuthSettings('SANDBOX',client_id='fixture',client_secret='secret-fixture',refresh_token='refresh-fixture',scopes=REQUIRED_SCOPES)
        with patch.object(SandboxHTTP,'request',return_value={'access_token':'new-fixture'}) as http:
            self.assertEqual('new-fixture',OAuthClient(settings).refresh_access_token())
            self.assertEqual('/identity/v1/oauth2/token',http.call_args.args[1])
        self.assertNotIn('secret-fixture',repr(settings))
        with patch.dict(os.environ,{'EBAY_ENVIRONMENT':'PRODUCTION'}), patch.object(SandboxHTTP,'request') as http:
            with self.assertRaises(PublicationError): OAuthClient(settings).refresh_access_token()
            http.assert_not_called()

    def test_default_disabled(self):
        with patch.dict(os.environ,{'EBAY_ENABLE_SANDBOX_API':''}), patch('integrated_ebay.sandbox_http.setting',return_value=''):
            with self.assertRaises(PublicationError): sandbox_guard()


@unittest.skip('Live Sandbox credentials/test listing not configured; fake HTTP is not live Sandbox validation.')
class LiveSandboxVerification(unittest.TestCase):
    def test_live_sandbox_operations(self):
        pass
