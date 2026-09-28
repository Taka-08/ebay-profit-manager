"""Offline OAuth-contract tests. All tokens are fixtures; no eBay/DB access."""

from dataclasses import replace
import ctypes
import http.client
import io
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from integrated_ebay.ebay_api import OAuthClient, OAuthSettings, ProductionEbayProvider
from integrated_ebay.publication_provider import PublicationError
from integrated_ebay.sandbox_http import REQUIRED_SCOPES, SandboxHTTP, NoRedirect
from integrated_ebay.sandbox_oauth import SandboxConsent, OAuthSetupError, authorization_request_diagnostics
from scripts.sandbox_oauth_setup import SetupServer, PrivateClipboard


def settings():
    return OAuthSettings('SANDBOX', client_id='fixture-app', client_secret='fixture-secret',
                         redirect_name='fixture-runame', scopes=REQUIRED_SCOPES)


def tokens():
    return dict(access_token='fixture-access', refresh_token='fixture-refresh',
                expires_in=7200, refresh_token_expires_in=47304000)


def callback(flow, code='fixture-code%2B+/#'):
    state = parse_qs(urlsplit(flow.authorization_url).query)['state'][0]
    return 'https://signin.ebay.com/ws/eBayISAPI.dll?' + urlencode({'state': state, 'code': code})


class ConsentTests(unittest.TestCase):
    def test_authorization_request_preflight_accepts_only_current_sandbox_request(self):
        config = settings()
        url = SandboxConsent(config).authorization_url
        report = authorization_request_diagnostics(url, config)
        self.assertEqual('VALID', report['overall'])
        self.assertEqual('SANDBOX', report['endpoint'])
        self.assertEqual('MATCH', report['client_id_match'])
        self.assertEqual('RUNAME', report['redirect_uri_type'])
        self.assertEqual('MATCH', report['redirect_uri_match'])
        self.assertEqual('YES', report['scope_required'])
        self.assertEqual('NO', report['scope_unexpected'])
        self.assertEqual('NO', report['duplicate_parameters'])
        self.assertEqual('NO', report['double_encoding'])

    def test_authorization_request_preflight_rejects_mismatches_and_malformed_requests(self):
        config = settings()
        url = SandboxConsent(config).authorization_url
        parts = urlsplit(url)
        original = dict(parse_qsl(parts.query))

        def changed(**fields):
            return urlunsplit(parts._replace(query=urlencode({**original, **fields})))

        cases = (
            (changed(client_id='different-client'), 'client_id_match', 'MISMATCH'),
            (changed(redirect_uri='different-runame'), 'redirect_uri_match', 'MISMATCH'),
            (changed(scope=REQUIRED_SCOPES[0]), 'scope_required', 'NO'),
            (changed(scope=' '.join(REQUIRED_SCOPES) + ' unexpected'), 'scope_unexpected', 'YES'),
            (parts._replace(netloc='auth.ebay.com').geturl(), 'endpoint', 'OTHER'),
            (changed(redirect_uri='https://example.invalid/accepted'), 'redirect_uri_type', 'URL'),
            (url + '&client_id=another', 'duplicate_parameters', 'YES'),
            (changed(redirect_uri='fixture%2Druname'), 'double_encoding', 'YES'),
            (changed(state=''), 'state', 'MISSING'),
        )
        for request_url, key, expected in cases:
            with self.subTest(check=key):
                report = authorization_request_diagnostics(request_url, config)
                self.assertEqual(expected, report[key])
                self.assertEqual('INVALID', report['overall'])

    def test_authorization_request_preflight_returns_statuses_without_logging_identifiers(self):
        config = settings()
        url = SandboxConsent(config).authorization_url
        state = parse_qs(urlsplit(url).query)['state'][0]
        with (patch('sys.stdout', new_callable=io.StringIO) as stdout,
              patch('sys.stderr', new_callable=io.StringIO) as stderr):
            report = authorization_request_diagnostics(url, config)
        for forbidden in (config.client_id, config.client_secret, config.redirect_name, state, url):
            self.assertNotIn(forbidden, repr(report))
            self.assertNotIn(forbidden, stdout.getvalue())
            self.assertNotIn(forbidden, stderr.getvalue())

    def test_prepare_has_no_network_and_correct_scope_and_state(self):
        with patch('integrated_ebay.sandbox_http.build_opener') as opener:
            flow = OAuthClient(settings()).begin_sandbox_authorization()
            url = urlsplit(flow.authorization_url)
            q = parse_qs(url.query)
            self.assertEqual('auth.sandbox.ebay.com', url.hostname)
            self.assertEqual(['code'], q['response_type'])
            self.assertEqual(['fixture-runame'], q['redirect_uri'])
            self.assertEqual(set(REQUIRED_SCOPES), set(q['scope'][0].split()))
            self.assertNotEqual(flow.authorization_url, SandboxConsent(settings()).authorization_url)
            self.assertNotIn('fixture-secret', flow.authorization_url)
            self.assertNotIn('fixture-secret', repr(flow))
            opener.assert_not_called()

    def test_invalid_config_refused_before_network(self):
        invalid = [replace(settings(), environment='PRODUCTION'), replace(settings(), client_id=''),
                   replace(settings(), client_secret=''), replace(settings(), redirect_name=''),
                   replace(settings(), scopes=(REQUIRED_SCOPES[1],)),
                   replace(settings(), scopes=REQUIRED_SCOPES + ('extra-scope',)),
                   replace(settings(), client_id='user:pass'), replace(settings(), client_secret='bad\nsecret')]
        with patch('integrated_ebay.sandbox_http.build_opener') as opener:
            for config in invalid:
                with self.subTest(config=config), self.assertRaises(OAuthSetupError):
                    SandboxConsent(config)
            opener.assert_not_called()

    def test_requires_explicit_confirmation(self):
        flow = SandboxConsent(settings())
        with patch.object(SandboxHTTP, 'exchange_authorization_code') as exchange:
            with self.assertRaises(OAuthSetupError): flow.exchange(callback(flow))
            exchange.assert_not_called()

    def test_exchange_decodes_once_and_tokens_repr_hides_secrets(self):
        flow = SandboxConsent(settings())
        with patch.object(SandboxHTTP, 'exchange_authorization_code', return_value=tokens()) as exchange:
            result = flow.exchange(callback(flow), confirmed=True)
            self.assertEqual('fixture-code%2B+/#', exchange.call_args.args[1])
            self.assertEqual('fixture-refresh', result.refresh_token)
            self.assertEqual('fixture-access', result.access_token)
            self.assertNotIn('fixture-', repr(result))

    def test_bad_state_denial_and_bad_callback_do_not_dispatch(self):
        for kind in ('wrong-state', 'denied', 'duplicate-code', 'missing-state', 'http', 'fragment', 'bad-code'):
            with self.subTest(kind=kind):
                flow = SandboxConsent(settings())
                url = callback(flow)
                if kind == 'wrong-state': url = 'https://example.com/?code=fixture&state=wrong'
                if kind == 'denied': url += '&error=access_denied'
                if kind == 'duplicate-code': url += '&code=another'
                if kind == 'missing-state': url = 'https://example.com/?code=fixture'
                if kind == 'http': url = url.replace('https:', 'http:')
                if kind == 'fragment': url += '#fragment'
                if kind == 'bad-code': url = callback(flow, 'bad\ncode')
                with patch.object(SandboxHTTP, 'exchange_authorization_code') as exchange:
                    with self.assertRaises(OAuthSetupError) as caught: flow.exchange(url, confirmed=True)
                    self.assertNotIn('fixture', str(caught.exception))
                    exchange.assert_not_called()

    def test_expired_flow_no_dispatch(self):
        flow = SandboxConsent(settings())
        with patch('integrated_ebay.sandbox_oauth.time.monotonic', return_value=flow._started + 601), patch.object(SandboxHTTP, 'exchange_authorization_code') as exchange:
            with self.assertRaises(OAuthSetupError): flow.exchange(callback(flow), confirmed=True)
            exchange.assert_not_called()

    def test_double_exchange_one_request_including_concurrent_calls(self):
        flow = SandboxConsent(settings())
        def exchange_once():
            try:
                flow.exchange(callback(flow), confirmed=True)
                return True
            except OAuthSetupError:
                return False
        with patch.object(SandboxHTTP, 'exchange_authorization_code', return_value=tokens()) as exchange:
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual([False, True], sorted(pool.map(lambda _: exchange_once(), range(2))))
            self.assertEqual(1, exchange.call_count)

    def test_timeout_no_retry_or_secret_leak(self):
        flow = SandboxConsent(settings())
        with patch.object(SandboxHTTP, 'exchange_authorization_code', side_effect=TimeoutError('fixture-secret')) as exchange:
            for _ in range(2):
                with self.assertRaises(OAuthSetupError) as caught: flow.exchange(callback(flow), confirmed=True)
                self.assertNotIn('fixture-secret', str(caught.exception))
                self.assertIsNone(caught.exception.__cause__)
            self.assertEqual(1, exchange.call_count)

    def test_malformed_token_result_is_not_success(self):
        for result in ({}, [], dict(tokens(), refresh_token='N/A'), dict(tokens(), refresh_token=''),
                       dict(tokens(), expires_in=True), dict(tokens(), refresh_token_expires_in=-1)):
            with patch.object(SandboxHTTP, 'exchange_authorization_code', return_value=result):
                flow = SandboxConsent(settings())
                with self.assertRaises(OAuthSetupError): flow.exchange(callback(flow), confirmed=True)


class TransportTests(unittest.TestCase):
    def test_fixed_sandbox_endpoint_basic_header_and_form(self):
        with patch('integrated_ebay.sandbox_http.build_opener') as opener:
            response = opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value = b'{}'
            SandboxHTTP().exchange_authorization_code(settings(), 'fixture+code%')
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual('https://api.sandbox.ebay.com/identity/v1/oauth2/token', request.full_url)
            self.assertEqual('POST', request.method)
            self.assertEqual({'grant_type': ['authorization_code'], 'code': ['fixture+code%'],
                              'redirect_uri': ['fixture-runame']}, parse_qs(request.data.decode()))
            self.assertTrue(request.get_header('Authorization').startswith('Basic '))
            self.assertIsInstance(opener.call_args.args[1], NoRedirect)
            self.assertEqual({}, opener.call_args.args[0].proxies)

    def test_production_settings_rejected_before_http(self):
        with patch('integrated_ebay.sandbox_http.build_opener') as opener:
            with self.assertRaises(OAuthSetupError):
                SandboxHTTP().exchange_authorization_code(replace(settings(), environment='PRODUCTION'), 'fixture')
            opener.assert_not_called()

    def test_inventory_guards_not_enabled_by_oauth_setup(self):
        with patch('integrated_ebay.sandbox_http.setting', return_value=''), patch('integrated_ebay.ebay_api.execution_mode', return_value='MOCK'), patch('integrated_ebay.sandbox_http.build_opener') as opener:
            OAuthClient(settings()).begin_sandbox_authorization()
            with self.assertRaises(PublicationError):
                SandboxHTTP().request('POST', '/sell/inventory/v1/offer/123/withdraw', write=True)
            with self.assertRaises(PublicationError): ProductionEbayProvider().update_price({})
            opener.assert_not_called()

    def test_transport_failure_sanitized_no_retry(self):
        for error in (TimeoutError('fixture-secret'), HTTPError('https://api.sandbox.ebay.com', 401, 'fixture-secret', {}, None),
                      HTTPError('https://api.sandbox.ebay.com', 302, 'fixture-secret', {}, None)):
            with patch('integrated_ebay.sandbox_http.build_opener') as opener:
                opener.return_value.open.side_effect = error
                with self.assertRaises(PublicationError) as caught:
                    SandboxHTTP().exchange_authorization_code(settings(), 'fixture')
                self.assertNotIn('fixture-secret', str(caught.exception))
                self.assertEqual(1, opener.return_value.open.call_count)


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.server = SetupServer()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.server.shutdown)

    def request(self, path='/', fields=None, *, origin=None):
        c = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        headers = {'Origin': origin or self.server.origin, 'Content-Type': 'application/x-www-form-urlencoded'}
        c.request('GET' if fields is None else 'POST', path, body=None if fields is None else urlencode(fields), headers=headers)
        response = c.getresponse()
        result = (response.status, dict(response.getheaders()), response.read().decode())
        c.close()
        return result

    def begin(self):
        return self.request('/begin', dict(csrf=self.server.csrf, sandbox='on', client_id='fixture-app',
                                          client_secret='fixture-secret', redirect_name='fixture-runame'))

    def test_helper_binds_only_loopback_and_page_no_cache(self):
        self.assertEqual('127.0.0.1', self.server.server_address[0])
        status, headers, html = self.request()
        self.assertEqual(200, status)
        self.assertEqual('no-store', headers['Cache-Control'])
        self.assertEqual('same-origin', headers['Referrer-Policy'])
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertIn('type="password"', html)
        self.assertNotIn('value="fixture', html)

    def test_csrf_and_cross_origin_refused(self):
        with patch('integrated_ebay.sandbox_http.build_opener') as opener:
            self.assertEqual(403, self.request('/begin', {'csrf': 'bad'})[0])
            self.assertEqual(403, self.request('/begin', {'csrf': self.server.csrf}, origin='https://example.com')[0])
            opener.assert_not_called()

    def test_no_callback_url_in_local_route(self):
        self.assertEqual(404, self.request('/?code=fixture-code')[0])

    def test_browser_flow_never_displays_tokens_or_saves_to_db(self):
        with patch('app_database.get_database_connection', side_effect=AssertionError('DB forbidden')), patch.object(SandboxHTTP, 'exchange_authorization_code', return_value=tokens()) as exchange, patch.object(PrivateClipboard, 'copy') as copy:
            self.assertEqual(303, self.begin()[0])
            self.assertNotIn('fixture-secret', self.request()[2])
            url = callback(self.server.flow)
            fields = dict(csrf=self.server.csrf, callback=url, confirmed='on')
            self.assertEqual(303, self.request('/exchange', fields)[0])
            html = self.request()[2]
            for private in ('fixture-access', 'fixture-refresh', 'fixture-secret', 'fixture-code'):
                self.assertNotIn(private, html)
            self.assertIsNone(self.server.flow)
            self.assertEqual('fixture-refresh', self.server.refresh)
            self.request('/exchange', fields)
            self.assertEqual(1, exchange.call_count)
            self.request('/copy', dict(csrf=self.server.csrf, private='on'))
            copy.assert_called_once_with('fixture-refresh')
            self.request('/reset', dict(csrf=self.server.csrf))
            self.assertIsNone(self.server.refresh)

    def test_callback_and_errors_not_logged(self):
        with patch('sys.stderr', new_callable=io.StringIO) as stderr, patch.object(SandboxHTTP, 'exchange_authorization_code', side_effect=ValueError('fixture-secret')):
            self.begin()
            self.request('/exchange', dict(csrf=self.server.csrf, callback=callback(self.server.flow), confirmed='on'))
            self.assertNotIn('fixture-secret', self.request()[2])
            self.assertEqual('', stderr.getvalue())

    def test_clipboard_auto_clear_does_not_clear_someone_elses_content(self):
        clipboard = PrivateClipboard()
        user = MagicMock()
        user.OpenClipboard.return_value = True
        user.GetClipboardSequenceNumber.return_value = 100
        clipboard.sequence = 99
        with patch.object(clipboard, '_api', return_value=(user, MagicMock())):
            clipboard.clear(force=True)
        user.EmptyClipboard.assert_not_called()

    def test_clipboard_auto_clear_own_content(self):
        clipboard = PrivateClipboard()
        user = MagicMock()
        user.OpenClipboard.return_value = True
        user.GetClipboardSequenceNumber.return_value = 99
        clipboard.sequence = 99
        with patch.object(clipboard, '_api', return_value=(user, MagicMock())):
            clipboard.clear(force=True)
        user.EmptyClipboard.assert_called_once()

    def test_clipboard_copy_excludes_history_and_cloud_without_system_clipboard(self):
        clipboard = PrivateClipboard()
        user, kernel = MagicMock(), MagicMock()
        user.CreateWindowExW.return_value = 123
        user.OpenClipboard.return_value = True
        user.EmptyClipboard.return_value = True
        user.RegisterClipboardFormatW.side_effect = [1001, 1002]
        user.SetClipboardData.return_value = 456
        user.GetClipboardSequenceNumber.return_value = 99
        buffer = ctypes.create_string_buffer(200)
        kernel.GlobalAlloc.return_value = 456
        kernel.GlobalLock.return_value = ctypes.addressof(buffer)
        with patch.object(clipboard, '_api', return_value=(user, kernel)):
            clipboard.copy('fixture-refresh')
        user.OpenClipboard.assert_called_once_with(123)
        self.assertEqual(['CanIncludeInClipboardHistory', 'CanUploadToCloudClipboard'],
                         [call.args[0] for call in user.RegisterClipboardFormatW.call_args_list])
        self.assertEqual([1001, 1002, 13], [call.args[0] for call in user.SetClipboardData.call_args_list])
        self.assertEqual(99, clipboard.sequence)
        user.DestroyWindow.assert_called_once_with(123)


if __name__ == '__main__':
    unittest.main()
