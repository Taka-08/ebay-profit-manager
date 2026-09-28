"""No redirects, retries, production host or caller-supplied URL. No response logging."""

import json
import os
import re
import base64
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

from app_database import _secret_value
from .publication_provider import PublicationError
from .sandbox_oauth_diagnostics import mark

BASE_SCOPE = 'https://api.ebay.com/oauth/api_scope'
REQUIRED_SCOPES = (BASE_SCOPE, BASE_SCOPE + '/sell.inventory')


def setting(name):
    return os.environ.get(name) or _secret_value(name, 'ebay') or ''


def sandbox_guard():
    from .ebay_api import execution_mode
    if (execution_mode() != 'SANDBOX' or setting('EBAY_ENVIRONMENT').upper() != 'SANDBOX'
            or setting('EBAY_ENABLE_SANDBOX_API').lower() != 'true'
            or setting('EBAY_ENABLE_PRODUCTION_WRITES').lower() not in ('', 'false')):
        raise PublicationError('DISABLED', 'Sandbox通信は明示設定が必要です。Production通信は禁止しています。')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class SandboxHTTP:
    def exchange_authorization_code(self, settings, code):
        # This capability has one fixed endpoint, independent of Inventory API flags.
        from .sandbox_oauth import validate_settings, validate_code
        validate_settings(settings)
        validate_code(code)
        auth = base64.b64encode((settings.client_id + ':' + settings.client_secret).encode()).decode()
        return self._send('POST', '/identity/v1/oauth2/token', headers={
            'Authorization': 'Basic ' + auth,
            'Content-Type': 'application/x-www-form-urlencoded',
        }, body=urlencode({'grant_type': 'authorization_code', 'code': code,
                           'redirect_uri': settings.redirect_name}).encode())

    def request(self, method, path, *, token='', body=None, headers=None, write=False):
        sandbox_guard()
        allowed = ((method == 'GET' and re.fullmatch(r'/sell/inventory/v1/(offer(?:\?sku=[^#]+|/[0-9]+)|inventory_item/[^/?#]+)', path))
                   or (method == 'POST' and path in ('/identity/v1/oauth2/token', '/ws/api.dll'))
                   or (method == 'POST' and write and (path == '/sell/inventory/v1/bulk_update_price_quantity'
                       or re.fullmatch(r'/sell/inventory/v1/offer/[0-9]+/withdraw', path))))
        if not allowed:
            raise PublicationError('DISABLED', '許可されていないAPI操作です。')
        hdr = dict(headers or {})
        if path == '/ws/api.dll' and hdr.get('X-EBAY-API-CALL-NAME') not in ('GetUser', 'GetUserPreferences'):
            raise PublicationError('DISABLED', 'Trading書き込みは無効です。')
        if token:
            if '\n' in token or '\r' in token:
                raise PublicationError('INVALID', '認証設定を確認してください。')
            hdr['Authorization'] = 'Bearer ' + token
        if isinstance(body, dict):
            body = json.dumps(body, allow_nan=False).encode('utf-8')
            hdr['Content-Type'] = 'application/json'
        return self._send(method, path, body=body, headers=hdr, write=write)

    def _send(self, method, path, *, body=None, headers=None, write=False):
        try:
            request = Request('https://api.sandbox.ebay.com' + path, data=body, headers=headers or {}, method=method)
            # Environment proxies and redirects must not move tokens to another host.
            with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=20) as response:
                raw = response.read(2_000_001)
                if path == '/identity/v1/oauth2/token':
                    mark('token_exchange_http_status', '2xx')
                if len(raw) > 2_000_000:
                    raise ValueError('Response too large')
                return raw if path == '/ws/api.dll' else json.loads(raw) if raw else {}
        except HTTPError as exc:
            if path == '/identity/v1/oauth2/token' and 400 <= exc.code < 600:
                mark('token_exchange_http_status', '4xx' if exc.code < 500 else '5xx')
            code = 'AUTH_EXPIRED' if exc.code in (401, 403) else 'RATE_LIMIT' if exc.code == 429 else 'FAILED'
            # Even an error response after dispatch can follow a partial change.
            raise PublicationError(code, 'eBay APIが要求を拒否しました。詳細な応答は表示しません。', uncertain=write) from None
        except Exception as exc:
            if (path == '/identity/v1/oauth2/token'
                    and (isinstance(exc, TimeoutError)
                         or isinstance(exc, URLError) and isinstance(exc.reason, TimeoutError))):
                mark('token_exchange_http_status', 'TIMEOUT')
            raise PublicationError('UNKNOWN_RESULT' if write else 'READ_FAILED',
                'eBay通信結果を確認できません。自動再送はしません。', uncertain=write) from None
