"""Offline checks for the temporary Developer Portal Sandbox User token path."""

import os
import secrets
import unittest
from unittest.mock import patch

from integrated_ebay.ebay_api import OAuthClient, OAuthSettings
from integrated_ebay.publication_provider import PublicationError
from integrated_ebay.sandbox_http import REQUIRED_SCOPES, SandboxHTTP
from integrated_ebay.sandbox_inventory import SandboxInventoryProvider


SANDBOX_ENV = {
    'EBAY_EXECUTION_MODE': 'SANDBOX',
    'EBAY_ENVIRONMENT': 'SANDBOX',
    'EBAY_ENABLE_SANDBOX_API': 'true',
    'EBAY_ENABLE_PRODUCTION_WRITES': 'false',
}


class PortalTokenTests(unittest.TestCase):
    def setUp(self):
        self.token = secrets.token_urlsafe(24)

    def test_sandbox_secret_is_explicit_and_does_not_fall_back_to_old_token(self):
        def secret(name, group):
            self.assertEqual('ebay', group)
            return self.token if name == 'EBAY_SANDBOX_USER_ACCESS_TOKEN' else ''

        with patch.dict(os.environ, {}, clear=True), patch('integrated_ebay.ebay_api._secret_value', side_effect=secret):
            settings = OAuthSettings.load('SANDBOX')
        self.assertEqual(self.token, settings.access_token)
        self.assertNotIn(self.token, repr(settings))

        with (patch.dict(os.environ, {'EBAY_SANDBOX_ACCESS_TOKEN': self.token}, clear=True),
              patch('integrated_ebay.ebay_api._secret_value', return_value='')):
            self.assertEqual('', OAuthSettings.load('SANDBOX').access_token)

    def test_portal_token_precedes_refresh_without_token_endpoint(self):
        settings = OAuthSettings('SANDBOX', refresh_token=secrets.token_urlsafe(24),
                                 access_token=self.token, scopes=REQUIRED_SCOPES)
        with (patch.dict(os.environ, {**SANDBOX_ENV, 'EBAY_SANDBOX_SELLER_EIAS': 'fixture-eias',
                                     'EBAY_SANDBOX_SELLER_USER_ID': 'fixture-user',
                                     'EBAY_SANDBOX_ALLOWED_OFFER_IDS': '1001'}, clear=True),
              patch('integrated_ebay.ebay_api.OAuthClient.refresh_access_token',
                    side_effect=AssertionError('refresh must not be used'))):
            self.assertEqual(self.token, SandboxInventoryProvider(settings=settings)._access_token())

    def test_first_probe_is_one_read_only_sandbox_call_with_no_db_or_refresh(self):
        settings = OAuthSettings('SANDBOX', access_token=self.token, scopes=REQUIRED_SCOPES)
        with (patch.dict(os.environ, SANDBOX_ENV, clear=True),
              patch.object(SandboxHTTP, 'request', return_value={'version': 'fixture-version'}) as request,
              patch('integrated_ebay.ebay_api.OAuthClient.refresh_access_token',
                    side_effect=AssertionError('refresh must not be used')),
              patch('app_database.get_database_connection', side_effect=AssertionError('DB must not be used'))):
            self.assertTrue(OAuthClient(settings).verify_sandbox_user_access_token())
        request.assert_called_once_with('GET', '/sell/inventory/v1/getVersion',
                                        token=self.token, write=False)

    def test_missing_or_invalid_direct_token_fails_without_fallback(self):
        for token in ('', ' ' + self.token, self.token + '\n'):
            settings = OAuthSettings('SANDBOX', refresh_token=secrets.token_urlsafe(24),
                                     access_token=token, scopes=REQUIRED_SCOPES)
            with (self.subTest(token_configured=bool(token)),
                  patch.dict(os.environ, SANDBOX_ENV, clear=True),
                  patch.object(SandboxHTTP, 'request') as request,
                  patch('integrated_ebay.ebay_api.OAuthClient.refresh_access_token') as refresh):
                with self.assertRaises(PublicationError):
                    OAuthClient(settings).verify_sandbox_user_access_token()
                request.assert_not_called()
                refresh.assert_not_called()

    def test_production_or_disabled_sandbox_cannot_probe(self):
        for environment in ('MOCK', 'PRODUCTION'):
            with (self.subTest(environment=environment),
                  patch.dict(os.environ, {**SANDBOX_ENV, 'EBAY_EXECUTION_MODE': environment}, clear=True),
                  patch.object(SandboxHTTP, 'request') as request):
                with self.assertRaises(PublicationError):
                    OAuthClient(OAuthSettings('SANDBOX', access_token=self.token,
                                              scopes=REQUIRED_SCOPES)).verify_sandbox_user_access_token()
                request.assert_not_called()
        with (patch.dict(os.environ, SANDBOX_ENV, clear=True),
              patch.object(SandboxHTTP, 'request') as request):
            with self.assertRaises(PublicationError):
                OAuthClient(OAuthSettings('PRODUCTION', access_token=self.token,
                                          scopes=REQUIRED_SCOPES)).verify_sandbox_user_access_token()
            request.assert_not_called()

    def test_probe_checks_result_and_does_not_expose_token(self):
        settings = OAuthSettings('SANDBOX', access_token=self.token, scopes=REQUIRED_SCOPES)
        with (patch.dict(os.environ, SANDBOX_ENV, clear=True),
              patch.object(SandboxHTTP, 'request', return_value={})):
            with self.assertRaises(PublicationError) as error:
                OAuthClient(settings).verify_sandbox_user_access_token()
        self.assertNotIn(self.token, str(error.exception))

    def test_http_host_is_fixed_and_get_cannot_be_marked_write(self):
        with patch.dict(os.environ, SANDBOX_ENV, clear=True), patch('integrated_ebay.sandbox_http.build_opener') as opener:
            response = opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value = b'{"version":"fixture-version"}'
            self.assertEqual({'version': 'fixture-version'}, SandboxHTTP().request(
                'GET', '/sell/inventory/v1/getVersion', token=self.token, write=False))
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual('https://api.sandbox.ebay.com/sell/inventory/v1/getVersion', request.full_url)
            self.assertIn(self.token, request.headers['Authorization'])
            with self.assertRaises(PublicationError):
                SandboxHTTP().request('GET', '/sell/inventory/v1/getVersion', token=self.token, write=True)
            self.assertEqual(1, opener.return_value.open.call_count)


if __name__ == '__main__':
    unittest.main()
