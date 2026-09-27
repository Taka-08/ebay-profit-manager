"""Offline Cloud-callback tests: no eBay network or production database."""

from concurrent.futures import ThreadPoolExecutor
import io
import sqlite3
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from ebay_listing_manager import streamlit_app as manager
from integrated_ebay import sandbox_callback_ui as ui
from integrated_ebay.ebay_api import OAuthSettings
from integrated_ebay.sandbox_callback import SandboxCallbackRegistry
from integrated_ebay.sandbox_http import REQUIRED_SCOPES, SandboxHTTP
from integrated_ebay.sandbox_oauth import OAuthSetupError


def settings():
    return OAuthSettings('SANDBOX', client_id='fixture-app', client_secret='fixture-secret',
                         redirect_name='fixture-runame', scopes=REQUIRED_SCOPES)


def state_from(url):
    return parse_qs(urlsplit(url).query)['state'][0]


def fixture_tokens():
    return {'access_token': 'fixture-access', 'refresh_token': 'fixture-refresh',
            'expires_in': 7200, 'refresh_token_expires_in': 47304000}


class QueryParams(dict):
    def __init__(self, values=None):
        super().__init__(values or {})
        self.clear_count = 0

    def get_all(self, key):
        return self.get(key, [])

    def clear(self):
        self.clear_count += 1
        super().clear()


class RerunSignal(Exception):
    pass


class FakeStreamlit:
    def __init__(self, query=None):
        self.query_params = QueryParams(query)
        self.session_state = {}
        self.screen = []
        self.inputs = []
        self.clicked = set()
        self.confirmed = False
        self.supplied = ''

    def title(self, value):
        self.screen.append(value)

    warning = title
    error = title
    info = title
    success = title
    caption = title

    def text_input(self, label, **kwargs):
        self.inputs.append((label, kwargs))
        return self.supplied

    def checkbox(self, label):
        return self.confirmed

    def button(self, label, on_click=None):
        clicked = label in self.clicked
        if clicked and on_click is not None:
            on_click()
        return clicked

    def link_button(self, label, url):
        self.screen.append(label)

    def rerun(self):
        raise RerunSignal()


class CallbackRegistryTests(unittest.TestCase):
    def test_state_matching_single_exchange_and_concurrent_replay(self):
        registry = SandboxCallbackRegistry()
        url = registry.begin(settings())
        self.assertEqual('auth.sandbox.ebay.com', urlsplit(url).hostname)
        state = state_from(url)
        with patch.object(SandboxHTTP, 'exchange_authorization_code', return_value=fixture_tokens()) as exchange:
            def attempt(_):
                try:
                    return registry.exchange(state, 'fixture-code').refresh_token
                except OAuthSetupError:
                    return None
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual([None, 'fixture-refresh'], sorted(pool.map(attempt, range(2)), key=str))
            exchange.assert_called_once()

    def test_bad_or_expired_state_no_dispatch(self):
        registry = SandboxCallbackRegistry()
        url = registry.begin(settings())
        with patch.object(SandboxHTTP, 'exchange_authorization_code') as exchange:
            with self.assertRaises(OAuthSetupError):
                registry.exchange('wrong-state', 'fixture-code')
            with patch('integrated_ebay.sandbox_callback.time.monotonic',
                       return_value=time.monotonic() + 601):
                with self.assertRaises(OAuthSetupError):
                    registry.exchange(state_from(url), 'fixture-code')
            exchange.assert_not_called()

    def test_code_required_and_reuse_across_flows_rejected(self):
        registry = SandboxCallbackRegistry()
        state1 = state_from(registry.begin(settings()))
        state2 = state_from(registry.begin(settings()))
        with patch.object(SandboxHTTP, 'exchange_authorization_code', return_value=fixture_tokens()) as exchange:
            with self.assertRaises(OAuthSetupError):
                registry.exchange(state1, '')
            registry.exchange(state1, 'fixture-code')
            with self.assertRaises(OAuthSetupError):
                registry.exchange(state2, 'fixture-code')
            exchange.assert_called_once()

    def test_failed_or_unknown_exchange_is_never_retried(self):
        registry = SandboxCallbackRegistry()
        state = state_from(registry.begin(settings()))
        with patch.object(SandboxHTTP, 'exchange_authorization_code',
                          side_effect=TimeoutError('fixture-secret')) as exchange:
            for _ in range(2):
                with self.assertRaises(OAuthSetupError) as caught:
                    registry.exchange(state, 'fixture-code')
                self.assertNotIn('fixture-secret', str(caught.exception))
            exchange.assert_called_once()

    def test_production_settings_cannot_start(self):
        registry = SandboxCallbackRegistry()
        with patch.object(SandboxHTTP, 'exchange_authorization_code') as exchange:
            with self.assertRaises(OAuthSetupError):
                registry.begin(OAuthSettings('PRODUCTION', client_id='fixture-app',
                    client_secret='fixture-secret', redirect_name='fixture-runame', scopes=REQUIRED_SCOPES))
            exchange.assert_not_called()


class CallbackPageTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeStreamlit()
        self.registry = SandboxCallbackRegistry()
        for context in (patch.object(ui, 'st', self.fake),
                        patch.object(ui, 'sandbox_callback_registry', self.registry),
                        patch.object(ui, 'setting', side_effect=lambda key: 'x' * 40 if key ==
                                     'EBAY_SANDBOX_OAUTH_SETUP_KEY' else ''),
                        patch.object(ui, 'execution_mode', return_value='MOCK'),
                        patch.object(manager, 'init_db', side_effect=AssertionError('init_db forbidden')),
                        patch.object(manager, 'get_connection', side_effect=AssertionError('DB forbidden'))):
            context.start()
            self.addCleanup(context.stop)

    def test_accepted_query_removed_before_exchange_and_token_masked(self):
        state = state_from(self.registry.begin(settings()))
        self.fake.query_params = QueryParams({'state': [state], 'code': ['fixture-code']})
        with patch.object(SandboxHTTP, 'exchange_authorization_code', return_value=fixture_tokens()) as exchange:
            ui.render_accepted()
            self.assertEqual(1, self.fake.query_params.clear_count)
            self.assertEqual({}, self.fake.query_params)
            exchange.assert_not_called()
            self.fake.supplied = 'x' * 40
            self.fake.confirmed = True
            self.fake.clicked.add('Sandbox Tokenを取得')
            with self.assertRaises(RerunSignal):
                ui.render_accepted()
            exchange.assert_called_once()
            self.fake.clicked.clear()
            ui.render_accepted()
            self.assertTrue(any(kwargs.get('type') == 'password' and
                                kwargs.get('value') == 'fixture-refresh' for _, kwargs in self.fake.inputs))
            screen = '\n'.join(self.fake.screen)
            for secret in ('fixture-code', 'fixture-refresh', 'fixture-access', 'fixture-secret', state):
                self.assertNotIn(secret, screen)

    def test_declined_and_missing_code_never_connect_or_exchange(self):
        with patch.object(SandboxHTTP, 'exchange_authorization_code') as exchange:
            self.fake.query_params = QueryParams({'state': ['fixture-state']})
            ui.render_accepted()
            self.assertEqual(1, self.fake.query_params.clear_count)
            self.fake.query_params = QueryParams({'state': ['fixture-state'], 'code': ['fixture-code']})
            ui.render_declined()
            self.assertEqual(1, self.fake.query_params.clear_count)
            exchange.assert_not_called()
        self.assertIn('Sandbox OAuthがキャンセルされました。', self.fake.screen)

    def test_duplicate_query_values_rejected_and_not_logged(self):
        self.fake.query_params = QueryParams({'state': ['a', 'b'], 'code': ['fixture-code']})
        with patch('sys.stderr', new_callable=io.StringIO) as stderr:
            ui.render_accepted()
        self.assertEqual(1, self.fake.query_params.clear_count)
        self.assertEqual('', stderr.getvalue())
        self.assertNotIn('fixture-code', '\n'.join(self.fake.screen))

    def test_public_or_production_configuration_fails_closed(self):
        with (patch.object(ui, 'execution_mode', return_value='PRODUCTION'),
              patch.object(SandboxHTTP, 'exchange_authorization_code') as exchange):
            self.fake.query_params = QueryParams({'state': ['fixture-state'], 'code': ['fixture-code']})
            ui.render_accepted()
            self.assertEqual(1, self.fake.query_params.clear_count)
            self.assertNotIn('_sandbox_oauth_callback', self.fake.session_state)
            exchange.assert_not_called()

    def test_refresh_handoff_can_be_cleared_and_expires_on_rerun(self):
        self.fake.session_state['_sandbox_oauth_refresh'] = ('fixture-refresh', time.monotonic())
        self.fake.clicked.add('受け渡しを終了')
        ui.render_accepted()
        self.assertNotIn('_sandbox_oauth_refresh', self.fake.session_state)
        self.assertNotIn('_sandbox_oauth_refresh_field', self.fake.session_state)
        self.fake.clicked.clear()
        self.fake.session_state['_sandbox_oauth_refresh'] = (
            'fixture-refresh', time.monotonic() - ui.TOKEN_HANDOFF_SECONDS - 1)
        ui.render_accepted()
        self.assertNotIn('_sandbox_oauth_refresh', self.fake.session_state)


class CallbackRoutingTests(unittest.TestCase):
    def test_registration_is_a_hidden_route_before_main(self):
        pages = []

        def page(function, **options):
            pages.append((function, options))
            return function

        with (patch.object(manager.st, 'Page', side_effect=page),
              patch.object(manager.st, 'navigation') as navigation,
              patch.object(manager, 'init_db', side_effect=AssertionError('init_db forbidden'))):
            manager.run_app()
        self.assertEqual('hidden', navigation.call_args.kwargs['position'])
        self.assertEqual(['ebay-sandbox-start', 'ebay-sandbox-accepted', 'ebay-sandbox-declined'],
                         [options['url_path'] for _, options in pages[1:]])
        self.assertTrue(pages[0][1]['default'])
        self.assertIs(pages[0][0], manager.main)

    def test_both_callback_routes_avoid_the_normal_page_and_all_db_connections(self):
        for route in (ui.ACCEPTED_PATH, ui.DECLINED_PATH):
            with self.subTest(route=route):
                fake = FakeStreamlit({'state': ['fixture-state'], 'code': ['fixture-code']})
                pages = []

                def page(function, **options):
                    pages.append((function, options))
                    return function

                class Navigation:
                    def run(self):
                        next(function for function, options in pages
                             if options.get('url_path') == route)()

                with (patch.object(ui, 'st', fake),
                      patch.object(ui, '_setup_key', side_effect=OAuthSetupError('not configured')),
                      patch.object(manager.st, 'Page', side_effect=page),
                      patch.object(manager.st, 'navigation', return_value=Navigation()),
                      patch.object(manager, 'main', side_effect=AssertionError('normal page forbidden')),
                      patch.object(manager, 'get_connection', side_effect=AssertionError('DB forbidden')),
                      patch('app_database.get_database_connection', side_effect=AssertionError('DB forbidden')),
                      patch.object(sqlite3, 'connect', side_effect=AssertionError('SQLite forbidden')),
                      patch.object(SandboxHTTP, 'exchange_authorization_code') as exchange):
                    manager.run_app()
                exchange.assert_not_called()
                self.assertEqual(1, fake.query_params.clear_count)
