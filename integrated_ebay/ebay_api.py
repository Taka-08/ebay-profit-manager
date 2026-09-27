"""Shared provider boundary. Live calls are Sandbox-only and explicitly opt-in."""

import json
import os
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Protocol

from app_database import _secret_value
from .change_safety import validate_remote
from .draft_repository import encode
from .migrations import utc_now
from .publication_provider import MockPublicationProvider, PublicationError, PublicationReceipt
from .sandbox_inventory import SandboxInventoryProvider as SandboxEbayProvider


MODES = ('MOCK', 'DRY_RUN', 'SANDBOX', 'PRODUCTION')


def execution_mode():
    mode = (os.environ.get('EBAY_EXECUTION_MODE') or _secret_value('EBAY_EXECUTION_MODE', 'ebay') or 'mock').upper()
    if mode not in MODES:
        raise ValueError('eBay実行モードが不正です。')
    return mode


def require_mock_execution(mode):
    if mode not in ('MOCK', 'DRY_RUN'):
        raise PublicationError('DISABLED', 'Mock/Dry-runのみ利用できます。Sandbox・Production・外部eBay通信は無効です。')


@dataclass(frozen=True)
class OAuthSettings:
    environment: str
    client_id: str = field(default='', repr=False)
    client_secret: str = field(default='', repr=False)
    refresh_token: str = field(default='', repr=False)
    access_token: str = field(default='', repr=False)
    redirect_name: str = field(default='', repr=False)
    scopes: tuple[str, ...] = ('https://api.ebay.com/oauth/api_scope/sell.inventory',)

    @classmethod
    def load(cls, environment):
        if environment not in ('SANDBOX', 'PRODUCTION'):
            raise ValueError('OAuth環境はSANDBOXまたはPRODUCTIONです。')
        def value(name):
            key = f'EBAY_{environment}_{name}'
            return os.environ.get(key) or _secret_value(key, 'ebay') or ''
        scopes = tuple(value('SCOPES').split())
        return cls(environment, *(value(name) for name in
                   ('CLIENT_ID', 'CLIENT_SECRET', 'REFRESH_TOKEN', 'ACCESS_TOKEN', 'REDIRECT_NAME')),
                   scopes=scopes)


class OAuthClient:
    def __init__(self, settings):
        self._settings = settings

    def authorize(self):
        raise PublicationError('DISABLED', 'OAuth認証は未有効です。別途承認が必要です。')

    def begin_sandbox_authorization(self):
        """Prepare a separate, OAuth-only consent flow; never enable listing APIs."""
        from .sandbox_oauth import SandboxConsent
        return SandboxConsent(self._settings)

    def refresh_access_token(self):
        import base64
        from urllib.parse import urlencode
        from .sandbox_http import sandbox_guard, SandboxHTTP, REQUIRED_SCOPES
        sandbox_guard()
        s = self._settings
        if (s.environment != 'SANDBOX' or not s.client_id or not s.client_secret or not s.refresh_token
                or not set(REQUIRED_SCOPES).issubset(s.scopes)):
            raise PublicationError('DISABLED', 'Sandboxの認証情報・scopeが不足しています。')
        auth = base64.b64encode((s.client_id + ':' + s.client_secret).encode()).decode()
        result = SandboxHTTP().request('POST', '/identity/v1/oauth2/token',
            headers={'Authorization': 'Basic ' + auth, 'Content-Type': 'application/x-www-form-urlencoded'},
            body=urlencode({'grant_type': 'refresh_token', 'refresh_token': s.refresh_token,
                            'scope': ' '.join(s.scopes)}).encode())
        if not isinstance(result.get('access_token'), str) or not result['access_token']:
            raise PublicationError('AUTH_EXPIRED', 'Sandboxトークンを取得できません。')
        # Caller holds only in memory. Never persist refreshed credentials automatically.
        return result['access_token']


class EbayProvider(Protocol):
    mode: str
    def create_listing(self, payload, *, idempotency_key): ...
    def revise_listing(self, payload, *, idempotency_key): ...
    def update_price(self, payload, *, idempotency_key): ...
    def update_quantity(self, payload, *, idempotency_key): ...
    def end_listing(self, payload, *, idempotency_key): ...
    def get_listing(self, external_listing_id): ...
    def lookup_execution(self, idempotency_key): ...


class MockEbayProvider(MockPublicationProvider):
    """Persistent simulated remote state; reused by the stage-5 publish Service."""
    def __init__(self, factory):
        self.factory = factory

    def get_listing(self, external_listing_id):
        require_mock_execution(self.mode)
        with self.factory() as c:
            row = c.execute('SELECT * FROM ebay_mock_listings WHERE external_listing_id=?', (external_listing_id,)).fetchone()
            return None if row is None else self._result(row)

    @staticmethod
    def _result(row):
        return dict(external_listing_id=row['external_listing_id'], payload=json.loads(row['payload_json']),
                    status=row['status'], version=row['version'])

    def lookup_execution(self, idempotency_key):
        require_mock_execution(self.mode)
        with self.factory() as c:
            row = c.execute('SELECT result_json FROM ebay_mock_receipts WHERE idempotency_key=?', (idempotency_key,)).fetchone()
            return json.loads(row[0]) if row else None

    def _apply(self, action, payload, key):
        require_mock_execution(self.mode)
        if not isinstance(key, str) or not key.strip():
            raise PublicationError('INVALID', '冪等キーが必要です。')
        hashed = sha256(encode(payload).encode()).hexdigest()
        with self.factory() as c:
            c.execute('BEGIN IMMEDIATE')
            previous = c.execute('SELECT * FROM ebay_mock_receipts WHERE idempotency_key=?', (key,)).fetchone()
            if previous:
                if previous['payload_hash'] != hashed or previous['action_type'] != action:
                    raise PublicationError('CONFLICT', '同じ冪等キーで別の処理は実行できません。')
                return json.loads(previous['result_json'])
            if action == 'CREATE_LISTING':
                item_id = 'MOCK-' + sha256(key.encode()).hexdigest()[:24]
                result = dict(external_listing_id=item_id, payload=payload, status='ACTIVE', version=1)
                c.execute('INSERT INTO ebay_mock_listings VALUES (?,?,?,?)', (item_id, encode(payload), 'ACTIVE', 1))
            else:
                item_id = payload['external_listing_id']
                row = c.execute('SELECT * FROM ebay_mock_listings WHERE external_listing_id=?', (item_id,)).fetchone()
                if row is None or row['status'] != 'ACTIVE' or row['version'] != payload['expected_revision']:
                    raise PublicationError('STALE', '出品状態が提案時から変わりました。再提案してください。')
                result = self._result(row)
                validate_remote(payload, result)
                result['payload'].update(payload.get('changes', {}))
                result.update(status='ENDED' if action == 'END_LISTING' else 'ACTIVE', version=row['version'] + 1)
                c.execute('UPDATE ebay_mock_listings SET payload_json=?,status=?,version=? WHERE external_listing_id=?',
                          (encode(result['payload']), result['status'], result['version'], item_id))
            c.execute('INSERT INTO ebay_mock_receipts VALUES (?,?,?,?,?)', (key, action, hashed, encode(result), utc_now()))
            return result

    def create_listing(self, payload, *, idempotency_key):
        return self._apply('CREATE_LISTING', payload, idempotency_key)

    def revise_listing(self, payload, *, idempotency_key):
        return self._apply('REVISE_LISTING', payload, idempotency_key)

    def update_price(self, payload, *, idempotency_key):
        return self._apply('UPDATE_PRICE', payload, idempotency_key)

    def update_quantity(self, payload, *, idempotency_key):
        return self._apply('UPDATE_QUANTITY', payload, idempotency_key)

    def end_listing(self, payload, *, idempotency_key):
        return self._apply('END_LISTING', payload, idempotency_key)

    def publish(self, payload, *, idempotency_key):
        return PublicationReceipt(self.create_listing(payload, idempotency_key=idempotency_key)['external_listing_id'])

    def lookup(self, idempotency_key):
        result = self.lookup_execution(idempotency_key)
        return PublicationReceipt(result['external_listing_id']) if result else None


class ProductionEbayProvider:
    mode = 'PRODUCTION'

    def _disabled(self, *args, **kwargs):
        raise PublicationError('DISABLED', '外部eBay APIは未接続です。今回は通信しません。')

    create_listing = revise_listing = update_price = update_quantity = end_listing = get_listing = lookup_execution = _disabled


def ebay_provider(factory, mode='MOCK'):
    if mode == 'MOCK':
        return MockEbayProvider(factory)
    if mode == 'SANDBOX':
        return SandboxEbayProvider(factory)
    if mode == 'PRODUCTION':
        return ProductionEbayProvider()
    raise ValueError('Dry-runは送信せずServiceで検証します。')
