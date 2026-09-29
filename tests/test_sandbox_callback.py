"""Offline Cloud-callback tests: no eBay network or production database."""

from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
import sqlite3
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from ebay_listing_manager import streamlit_app as manager
from integrated_ebay import sandbox_callback_ui as ui
from integrated_ebay.ebay_api import OAuthSettings
from integrated_ebay.sandbox_callback import SandboxCallbackRegistry
from integrated_ebay.sandbox_http import REQUIRED_SCOPES, SandboxHTTP
from integrated_ebay.sandbox_oauth import OAuthSetupError
from integrated_ebay.sandbox_oauth_diagnostics import diagnostic_scope, mark, new_diagnostic, safe_lines


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


class FakeStreamlit:
    def __init__(self, query=None):
        self.query_params = QueryParams(query)
        self.session_state = {}
        self.secrets = {}
        self.screen = []
        self.inputs = []
        self.clicked = set()
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

    def button(self, label, on_click=None):
        clicked = label in self.clicked
        if clicked and on_click is not None:
            on_click()
        return clicked

    def link_button(self, label, url):
        self.screen.append(label)

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

    def test_prepared_request_diagnostics_compare_generation_without_exposing_values(self):
        registry = SandboxCallbackRegistry()
        url = registry.begin(settings())
        state = state_from(url)
        same = registry.prepared_request_diagnostics(url)
        self.assertEqual({'state_match': 'MATCH', 'generated_url_match': 'MATCH'}, same)
        changed = registry.prepared_request_diagnostics(url + '&extra=fixture')
        self.assertEqual({'state_match': 'MATCH', 'generated_url_match': 'MISMATCH'}, changed)
        unknown = registry.prepared_request_diagnostics(url.replace(state, 'other-state'))
        self.assertEqual({'state_match': 'MISMATCH', 'generated_url_match': 'MISMATCH'}, unknown)
        with patch('integrated_ebay.sandbox_callback.time.monotonic', return_value=time.monotonic() + 601):
            expired = registry.prepared_request_diagnostics(url)
        self.assertEqual({'state_match': 'MISMATCH', 'generated_url_match': 'MISMATCH'}, expired)
        for status in (same, changed, unknown, expired):
            for forbidden in (settings().client_id, settings().redirect_name, state, url):
                self.assertNotIn(forbidden, repr(status))

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

    def test_accepted_exchanges_once_and_masks_token_after_query_clear(self):
        state = state_from(self.registry.begin(settings()))
        self.fake.query_params = QueryParams({'state': [state], 'code': ['fixture-code']})
        def exchange_after_clear(*_args):
            self.assertEqual({}, self.fake.query_params)
            return fixture_tokens()

        with patch.object(SandboxHTTP, 'exchange_authorization_code', side_effect=exchange_after_clear) as exchange:
            with patch.object(self.registry, 'exchange', wraps=self.registry.exchange) as callback_exchange:
                with (patch('sys.stdout', new_callable=io.StringIO) as stdout,
                      patch('sys.stderr', new_callable=io.StringIO) as stderr):
                    ui.render_accepted()
                    self.assertEqual(1, self.fake.query_params.clear_count)
                    callback_exchange.assert_called_once_with(state, 'fixture-code')
                    ui.render_accepted()
                    callback_exchange.assert_called_once()
            exchange.assert_called_once()
            self.assertTrue(any(kwargs.get('type') == 'password' and
                                kwargs.get('value') == 'fixture-refresh' for _, kwargs in self.fake.inputs))
            screen = '\n'.join(self.fake.screen)
            for secret in ('fixture-code', 'fixture-refresh', 'fixture-access', 'fixture-secret', state):
                self.assertNotIn(secret, screen)
                self.assertNotIn(secret, stdout.getvalue())
                self.assertNotIn(secret, stderr.getvalue())

    def test_start_diagnostics_identify_failure_without_exposing_values_or_dispatching(self):
        marker_values = {
            'EBAY_SANDBOX_CLIENT_ID': 'private-client-marker',
            'EBAY_SANDBOX_CLIENT_SECRET': 'private-secret-marker',
            'EBAY_SANDBOX_REDIRECT_NAME': 'private-runame-marker',
            'EBAY_SANDBOX_SCOPES': REQUIRED_SCOPES[0],
            'EBAY_SANDBOX_OAUTH_SETUP_KEY': 'private-short-key',
            'EBAY_ENABLE_PRODUCTION_WRITES': 'true',
            'EBAY_EXECUTION_MODE': 'PRODUCTION',
        }
        self.fake.secrets = {'ebay': marker_values}
        with (patch.dict(os.environ, {}, clear=True),
              patch.object(ui, '_setup_key', side_effect=OAuthSetupError('private-exception-marker')),
              patch.object(self.registry, 'begin') as begin,
              patch.object(SandboxHTTP, 'exchange_authorization_code') as exchange,
              patch('sys.stdout', new_callable=io.StringIO) as stdout,
              patch('sys.stderr', new_callable=io.StringIO) as stderr):
            ui.render_start()
        screen = '\n'.join(self.fake.screen)
        self.assertIn('EBAY_SANDBOX_CLIENT_ID: loaded=OK, format=OK, source=[ebay]', screen)
        self.assertIn('EBAY_SANDBOX_CLIENT_SECRET: loaded=OK, format=OK, source=[ebay]', screen)
        self.assertIn('EBAY_SANDBOX_REDIRECT_NAME: loaded=OK, format=OK, source=[ebay]', screen)
        self.assertIn('missing required scope: ' + REQUIRED_SCOPES[1], screen)
        self.assertIn('minimum 32 characters=NG - too short', screen)
        self.assertIn('EXECUTION_MODE: NG - Production mode', screen)
        self.assertIn('PRODUCTION_WRITE_GUARD: NG - writes not disabled', screen)
        for secret in (marker_values['EBAY_SANDBOX_CLIENT_ID'],
                       marker_values['EBAY_SANDBOX_CLIENT_SECRET'],
                       marker_values['EBAY_SANDBOX_REDIRECT_NAME'],
                       marker_values['EBAY_SANDBOX_OAUTH_SETUP_KEY'],
                       'private-exception-marker'):
            self.assertNotIn(secret, screen)
            self.assertNotIn(secret, stdout.getvalue())
            self.assertNotIn(secret, stderr.getvalue())
        self.assertFalse(self.fake.inputs)
        begin.assert_not_called()
        exchange.assert_not_called()

    def test_diagnostic_sources_and_matching_settings(self):
        self.fake.secrets = {
            'ebay': {
                'EBAY_SANDBOX_CLIENT_ID': 'shadowed-client',
                'EBAY_SANDBOX_CLIENT_SECRET': 'section-secret',
                'EBAY_SANDBOX_SCOPES': ' '.join(REQUIRED_SCOPES),
                'EBAY_SANDBOX_OAUTH_SETUP_KEY': 'k' * 32,
            },
            'EBAY_SANDBOX_REDIRECT_NAME': 'root-runame',
        }
        with patch.dict(os.environ, {'EBAY_SANDBOX_CLIENT_ID': 'environment-client'}, clear=True):
            lines = ui._configuration_diagnostics()
        screen = '\n'.join(lines)
        self.assertIn('EBAY_SANDBOX_CLIENT_ID: loaded=OK, format=OK, source=environment', screen)
        self.assertIn('EBAY_SANDBOX_CLIENT_SECRET: loaded=OK, format=OK, source=[ebay]', screen)
        self.assertIn('EBAY_SANDBOX_REDIRECT_NAME: loaded=OK, format=OK, source=top-level', screen)
        self.assertIn('EBAY_SANDBOX_SCOPES: loaded=OK, required scopes=OK, source=[ebay]', screen)
        self.assertIn('minimum 32 characters=OK, source=[ebay]', screen)
        self.assertIn('EXECUTION_MODE: OK - Sandbox OAuth allowed, source=missing', screen)
        self.assertIn('PRODUCTION_WRITE_GUARD: OK - writes disabled, source=missing', screen)
        for secret in ('shadowed-client', 'section-secret', 'root-runame', 'environment-client', 'k' * 32):
            self.assertNotIn(secret, screen)

    def test_diagnostics_respect_empty_section_shadow_and_code_format(self):
        self.fake.secrets = {'ebay': {'EBAY_SANDBOX_CLIENT_ID': ''},
                             'EBAY_SANDBOX_CLIENT_ID': 'root-client'}
        with patch.dict(os.environ, {'EBAY_EXECUTION_MODE': 'invalid-mode',
                                     'EBAY_ENABLE_PRODUCTION_WRITES': '0'}, clear=True):
            screen = '\n'.join(ui._configuration_diagnostics())
        self.assertIn('EBAY_SANDBOX_CLIENT_ID: loaded=NG, format=NG - not loaded, source=[ebay]', screen)
        self.assertIn('EXECUTION_MODE: NG - unsupported mode, source=environment', screen)
        self.assertIn('PRODUCTION_WRITE_GUARD: NG - writes not disabled, source=environment', screen)
        self.assertNotIn('root-client', screen)

    def test_diagnostics_identify_each_format_problem_without_values(self):
        self.fake.secrets = {'ebay': {
            'EBAY_SANDBOX_CLIENT_ID': 'private:client',
            'EBAY_SANDBOX_CLIENT_SECRET': 'private\nsecret',
            'EBAY_SANDBOX_REDIRECT_NAME': 'r' * 4097,
            'EBAY_SANDBOX_SCOPES': ' '.join(REQUIRED_SCOPES) + ' unexpected-scope',
            'EBAY_SANDBOX_OAUTH_SETUP_KEY': 'k' * 32,
        }}
        with patch.dict(os.environ, {}, clear=True):
            screen = '\n'.join(ui._configuration_diagnostics())
        self.assertIn('EBAY_SANDBOX_CLIENT_ID: loaded=OK, format=NG - contains a colon', screen)
        self.assertIn('EBAY_SANDBOX_CLIENT_SECRET: loaded=OK, format=NG - contains a control character', screen)
        self.assertIn('EBAY_SANDBOX_REDIRECT_NAME: loaded=OK, format=NG - exceeds 4096 characters', screen)
        self.assertIn('EBAY_SANDBOX_SCOPES: loaded=OK, required scopes=NG - unexpected scope configured', screen)
        for secret in ('private:client', 'private\nsecret', 'r' * 4097, 'unexpected-scope', 'k' * 32):
            self.assertNotIn(secret, screen)

    def test_valid_start_does_not_display_diagnostics_or_start_consent(self):
        with (patch.object(ui.OAuthSettings, 'load', return_value=settings()),
              patch.object(self.registry, 'begin') as begin):
            ui.render_start()
        self.assertEqual(['eBay Sandbox OAuth'], self.fake.screen)
        self.assertEqual('セットアップキー', self.fake.inputs[0][0])
        begin.assert_not_called()

    def test_prepared_request_shows_only_statuses_before_link_without_network(self):
        config = settings()
        sources = {
            'EBAY_SANDBOX_CLIENT_ID': (config.client_id, 'environment'),
            'EBAY_SANDBOX_REDIRECT_NAME': (config.redirect_name, '[ebay]'),
            'EBAY_SANDBOX_SCOPES': (' '.join(config.scopes), 'top-level'),
        }
        self.fake.clicked.add('Sandbox同意リンクを準備')
        self.fake.supplied = 'x' * 40
        with (patch.object(ui.OAuthSettings, 'load', return_value=config),
               patch.object(ui, '_diagnostic_setting', side_effect=sources.get),
               patch.object(ui, 'authorization_request_diagnostics',
                            wraps=ui.authorization_request_diagnostics) as diagnose,
               patch.object(self.fake, 'link_button', wraps=self.fake.link_button) as link,
               patch.object(SandboxHTTP, 'exchange_authorization_code') as exchange,
              patch('sys.stdout', new_callable=io.StringIO) as stdout,
              patch('sys.stderr', new_callable=io.StringIO) as stderr):
            ui.render_start()
        screen = '\n'.join(self.fake.screen)
        self.assertIn('Authorization request overall: VALID', screen)
        self.assertIn('Client ID source: environment', screen)
        self.assertIn('redirect_uri source: [ebay]', screen)
        self.assertIn('scope source: top-level', screen)
        self.assertIn('eBay Sandboxで同意する', screen)
        self.assertIn('Scheme: HTTPS', screen)
        self.assertIn('Host: EXPECTED_SANDBOX', screen)
        self.assertIn('Path: EXPECTED_AUTHORIZE_PATH', screen)
        self.assertIn('Query parameter count: 6', screen)
        self.assertIn('state matches prepared flow: MATCH', screen)
        self.assertIn('URL matches prepared flow: MATCH', screen)
        self.assertIn('encode/decode semantic roundtrip: YES', screen)
        self.assertIs(diagnose.call_args.args[0], link.call_args.args[1])
        url = self.fake.session_state['_sandbox_oauth_consent_url']
        state = state_from(url)
        for forbidden in (config.client_id, config.client_secret, config.redirect_name,
                          self.fake.supplied, state, url):
            self.assertNotIn(forbidden, screen)
            self.assertNotIn(forbidden, stdout.getvalue())
            self.assertNotIn(forbidden, stderr.getvalue())
        exchange.assert_not_called()

    def test_stale_request_mismatch_hides_link(self):
        self.fake.session_state['_sandbox_oauth_consent_url'] = self.registry.begin(settings())
        current = OAuthSettings('SANDBOX', client_id='changed-client', client_secret='fixture-secret',
                                redirect_name='fixture-runame', scopes=REQUIRED_SCOPES)
        sources = {
            'EBAY_SANDBOX_CLIENT_ID': (current.client_id, 'environment'),
            'EBAY_SANDBOX_REDIRECT_NAME': (current.redirect_name, '[ebay]'),
            'EBAY_SANDBOX_SCOPES': (' '.join(current.scopes), '[ebay]'),
        }
        with (patch.object(ui.OAuthSettings, 'load', return_value=current),
              patch.object(ui, '_diagnostic_setting', side_effect=sources.get)):
            ui.render_start()
        screen = '\n'.join(self.fake.screen)
        self.assertIn('Client ID match: MISMATCH', screen)
        self.assertIn('Authorization request overall: INVALID', screen)
        self.assertNotIn('eBay Sandboxで同意する', screen)
        self.assertNotIn('_sandbox_oauth_consent_url', self.fake.session_state)

    def test_unknown_runtime_source_hides_link(self):
        config = settings()
        self.fake.session_state['_sandbox_oauth_consent_url'] = self.registry.begin(config)
        sources = {
            'EBAY_SANDBOX_CLIENT_ID': ('different-client', 'environment'),
            'EBAY_SANDBOX_REDIRECT_NAME': (config.redirect_name, '[ebay]'),
            'EBAY_SANDBOX_SCOPES': (' '.join(config.scopes), '[ebay]'),
        }
        with (patch.object(ui.OAuthSettings, 'load', return_value=config),
              patch.object(ui, '_diagnostic_setting', side_effect=sources.get)):
            ui.render_start()
        screen = '\n'.join(self.fake.screen)
        self.assertIn('Client ID source: UNKNOWN', screen)
        self.assertIn('Authorization request overall: INVALID', screen)
        self.assertNotIn('eBay Sandboxで同意する', screen)

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

    def test_callback_reload_with_old_code_cannot_exchange_again(self):
        state = state_from(self.registry.begin(settings()))
        with patch.object(SandboxHTTP, 'exchange_authorization_code', return_value=fixture_tokens()) as exchange:
            self.fake.query_params = QueryParams({'state': [state], 'code': ['fixture-code']})
            ui.render_accepted()
            self.fake.query_params = QueryParams({'state': [state], 'code': ['fixture-code']})
            ui.render_accepted()
            exchange.assert_called_once()
            self.assertNotIn('_sandbox_oauth_refresh', self.fake.session_state)

    def test_timeout_does_not_retry_or_expose_details(self):
        state = state_from(self.registry.begin(settings()))
        self.fake.query_params = QueryParams({'state': [state], 'code': ['fixture-code']})
        with patch.object(SandboxHTTP, 'exchange_authorization_code',
                          side_effect=TimeoutError('fixture-secret')) as exchange:
            ui.render_accepted()
            self.assertEqual(1, self.fake.query_params.clear_count)
            self.assertNotIn('fixture-secret', '\n'.join(self.fake.screen))
            self.assertNotIn('fixture-code', '\n'.join(self.fake.screen))
            ui.render_accepted()
            exchange.assert_called_once()

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


class CallbackDiagnosticTests(unittest.TestCase):
    setUp = CallbackPageTests.setUp

    def test_missing_code_records_only_fixed_statuses(self):
        self.fake.query_params = QueryParams({'state': ['fixture-state'], 'expires_in': ['299']})
        with patch.object(SandboxHTTP, 'exchange_authorization_code') as exchange:
            ui.render_accepted()
            exchange.assert_not_called()
        diagnostic = self.fake.session_state['_sandbox_oauth_diagnostics'][-1]
        self.assertEqual('YES', diagnostic['callback_reached'])
        self.assertEqual('YES', diagnostic['state_received'])
        self.assertEqual('NO', diagnostic['code_received'])
        self.assertEqual('YES', diagnostic['query_cleared'])
        self.assertEqual('NOT ATTEMPTED', diagnostic['token_exchange_http_status'])
        self.assertNotIn('fixture-state', '\n'.join(self.fake.screen))

    def test_lost_or_expired_process_state_never_exchanges(self):
        state = state_from(self.registry.begin(settings()))
        self.registry._pending.clear()
        self.fake.query_params = QueryParams({'state': [state], 'code': ['fixture-code']})
        with patch.object(SandboxHTTP, 'exchange_authorization_code') as exchange:
            ui.render_accepted()
            exchange.assert_not_called()
        diagnostic = self.fake.session_state['_sandbox_oauth_diagnostics'][-1]
        self.assertEqual('NO', diagnostic['stored_state_found'])
        self.assertEqual('NOT CHECKED', diagnostic['state_matched'])
        self.assertEqual('UNKNOWN', diagnostic['same_cloud_process'])
        self.assertEqual('NO', diagnostic['token_exchange_attempted'])

        state = state_from(self.registry.begin(settings()))
        self.fake.query_params = QueryParams({'state': [state], 'code': ['fixture-code-2']})
        with (patch('integrated_ebay.sandbox_callback.time.monotonic',
                    return_value=time.monotonic() + 601),
              patch.object(SandboxHTTP, 'exchange_authorization_code') as exchange):
            ui.render_accepted()
            exchange.assert_not_called()
        diagnostic = self.fake.session_state['_sandbox_oauth_diagnostics'][-1]
        self.assertEqual('YES', diagnostic['stored_state_found'])
        self.assertEqual('YES', diagnostic['state_expired'])
        self.assertEqual('SAME', diagnostic['same_cloud_process'])
        self.assertEqual('NO', diagnostic['token_exchange_attempted'])

    def test_success_and_replayed_callback_remain_distinguishable(self):
        state = state_from(self.registry.begin(settings()))
        query = {'state': [state], 'code': ['fixture-code']}
        with patch.object(SandboxHTTP, 'exchange_authorization_code', return_value=fixture_tokens()) as exchange:
            self.fake.query_params = QueryParams(query)
            ui.render_accepted()
            self.fake.query_params = QueryParams(query)
            ui.render_accepted()
            exchange.assert_called_once()
        previous, latest = self.fake.session_state['_sandbox_oauth_diagnostics']
        self.assertEqual('YES', previous['token_exchange_succeeded'])
        self.assertEqual('YES', previous['refresh_token_received'])
        self.assertEqual('YES', latest['callback_already_processed'])
        self.assertEqual('YES', latest['rerun_detected_after_callback'])
        self.assertEqual('SAME', latest['same_cloud_process'])
        self.assertEqual('NO', latest['token_exchange_attempted'])
        self.assertNotIn('fixture-code', '\n'.join(self.fake.screen))
        self.assertNotIn(state, '\n'.join(self.fake.screen))

    def test_http_categories_and_invalid_response_without_network(self):
        cases = ((401, '4xx'), (503, '5xx'), (TimeoutError('fixture-secret'), 'TIMEOUT'),
                 (None, '2xx'))
        for failure, expected in cases:
            with self.subTest(expected=expected):
                self.fake.session_state.pop('_sandbox_oauth_diagnostics', None)
                state = state_from(self.registry.begin(settings()))
                self.fake.query_params = QueryParams({'state': [state], 'code': ['fixture-code-' + expected]})
                with patch('integrated_ebay.sandbox_http.build_opener') as opener:
                    if isinstance(failure, int):
                        opener.return_value.open.side_effect = HTTPError(
                            'https://api.sandbox.ebay.com', failure, 'denied', {}, None)
                    elif failure is not None:
                        opener.return_value.open.side_effect = failure
                    else:
                        opener.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(
                            dict(fixture_tokens(), refresh_token='N/A')).encode()
                    with patch('sys.stdout', new_callable=io.StringIO) as stdout, patch(
                            'sys.stderr', new_callable=io.StringIO) as stderr:
                        ui.render_accepted()
                    self.assertEqual('', stdout.getvalue())
                    self.assertEqual('', stderr.getvalue())
                    self.assertEqual(1, opener.return_value.open.call_count)
                diagnostic = self.fake.session_state['_sandbox_oauth_diagnostics'][-1]
                self.assertEqual('YES', diagnostic['token_exchange_attempted'])
                self.assertEqual(expected, diagnostic['token_exchange_http_status'])
                self.assertEqual('NO', diagnostic['token_exchange_succeeded'])
                if expected == '2xx':
                    self.assertEqual('NO', diagnostic['refresh_token_received'])
                self.assertNotIn('fixture-secret', '\n'.join(self.fake.screen))

    def test_http_success_records_complete_exchange_without_logging_values(self):
        state = state_from(self.registry.begin(settings()))
        self.fake.query_params = QueryParams({'state': [state], 'code': ['fixture-code']})
        with patch('integrated_ebay.sandbox_http.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(
                fixture_tokens()).encode()
            with patch('sys.stdout', new_callable=io.StringIO) as stdout, patch(
                    'sys.stderr', new_callable=io.StringIO) as stderr:
                ui.render_accepted()
            self.assertEqual('', stdout.getvalue())
            self.assertEqual('', stderr.getvalue())
            self.assertEqual(1, opener.return_value.open.call_count)
        diagnostic = self.fake.session_state['_sandbox_oauth_diagnostics'][-1]
        self.assertEqual('YES', diagnostic['stored_state_found'])
        self.assertEqual('YES', diagnostic['state_matched'])
        self.assertEqual('NO', diagnostic['state_expired'])
        self.assertEqual('2xx', diagnostic['token_exchange_http_status'])
        self.assertEqual('YES', diagnostic['token_exchange_succeeded'])
        self.assertEqual('YES', diagnostic['refresh_token_received'])
        for value in ('fixture-secret', 'fixture-code', 'fixture-access', 'fixture-refresh', state):
            self.assertNotIn(value, '\n'.join(self.fake.screen))

    def test_rerun_and_secret_value_cannot_be_rendered_as_diagnostic(self):
        state = state_from(self.registry.begin(settings()))
        self.fake.query_params = QueryParams({'state': [state], 'code': ['fixture-code']})
        with patch.object(SandboxHTTP, 'exchange_authorization_code', return_value=fixture_tokens()):
            ui.render_accepted()
        self.fake.query_params = QueryParams()
        ui.render_accepted()
        diagnostic = self.fake.session_state['_sandbox_oauth_diagnostics'][-1]
        self.assertEqual('YES', diagnostic['rerun_detected_after_callback'])
        poisoned = new_diagnostic()
        poisoned['state_received'] = 'fixture-secret'
        self.assertNotIn('fixture-secret', '\n'.join(safe_lines(poisoned)))

    def test_concurrent_diagnostics_are_session_isolated(self):
        first, second = new_diagnostic(), new_diagnostic()
        def record(diagnostic, value):
            with diagnostic_scope(diagnostic):
                mark('code_received', value)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda pair: record(*pair), ((first, 'YES'), (second, 'NO'))))
        self.assertEqual('YES', first['code_received'])
        self.assertEqual('NO', second['code_received'])
