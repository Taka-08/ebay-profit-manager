"""Inventory-only Sandbox changes. Trading calls are identity/preferences reads only."""

import json
import re
from decimal import Decimal
from hashlib import sha256
from urllib.parse import quote, urlencode
from xml.etree import ElementTree as ET

from .change_safety import BINDING_FIELDS, PRICE_PLACES, validate_local, validate_remote, validate_result
from .draft_repository import encode
from .migrations import utc_now
from .publication_provider import PublicationError
from .sandbox_http import SandboxHTTP, sandbox_guard, setting, REQUIRED_SCOPES

SUPPORTED = ('UPDATE_PRICE', 'UPDATE_QUANTITY', 'END_LISTING')
IDENTIFIERS = ('offer_id', 'seller_account', 'api_family', 'environment')
SITES = {'EBAY_US': 'USD', 'EBAY_CA': 'CAD', 'EBAY_GB': 'GBP', 'EBAY_AU': 'AUD',
         'EBAY_DE': 'EUR', 'EBAY_FR': 'EUR', 'EBAY_IT': 'EUR', 'EBAY_ES': 'EUR'}


def sandbox_binding(listing):
    target = {key: listing[key] for key in BINDING_FIELDS}
    saved = json.loads(listing['binding_json'])
    target.update({key: saved.get(key) for key in IDENTIFIERS})
    before = json.loads(listing['current_payload_json'])
    target['currency'] = before.get('currency')
    required = [v for k, v in target.items() if k not in ('listing_draft_id', 'publication_id')]
    if (any(not isinstance(v, str) or not v.strip() for v in required)
            or target['mode'] != 'SANDBOX' or target['environment'] != 'SANDBOX'
            or target['api_family'] != 'INVENTORY' or not re.fullmatch(r'[0-9]+', target['offer_id'])
            or not re.fullmatch(r'[0-9]+', target['external_listing_id'])
            or before.get('sku') != target['sku'] or before.get('site') != target['marketplace']
            or SITES.get(target['marketplace']) != target['currency']
            or any(before.get(k) != target[k] for k in IDENTIFIERS)):
        raise ValueError('Sandboxの出品・Offer・アカウント・通貨の紐付けが不正です。')
    return target


class SandboxInventoryProvider:
    mode = 'SANDBOX'

    def __init__(self, factory=None, *, http=None, settings=None):
        self.factory = factory
        self.http = http or SandboxHTTP()
        self._settings = settings
        self._token = None

    def check_enabled(self):
        sandbox_guard()
        from .ebay_api import OAuthSettings
        s = self._settings or OAuthSettings.load('SANDBOX')
        if (s.environment != 'SANDBOX' or not set(REQUIRED_SCOPES).issubset(s.scopes)
                or not (s.access_token or (s.client_id and s.client_secret and s.refresh_token))
                or not setting('EBAY_SANDBOX_SELLER_EIAS') or not setting('EBAY_SANDBOX_SELLER_USER_ID')
                or not setting('EBAY_SANDBOX_ALLOWED_OFFER_IDS')):
            raise PublicationError('DISABLED', 'Sandboxの認証・scope・seller・テストOffer許可設定が不足しています。')
        return s

    def _access_token(self):
        s = self.check_enabled()
        if self._token is None:
            from .ebay_api import OAuthClient
            self._token = s.access_token or OAuthClient(s).refresh_access_token()
        return self._token

    def _json(self, method, path, *, body=None, write=False):
        return self.http.request(method, '/sell/inventory/v1/' + path,
                                 token=self._access_token(), body=body, write=write)

    def _trading_read(self, call):
        if call not in ('GetUser', 'GetUserPreferences'):
            raise PublicationError('DISABLED', 'Trading書き込みは禁止しています。')
        field = '<ShowOutOfStockControlPreference>true</ShowOutOfStockControlPreference>' if call == 'GetUserPreferences' else ''
        raw = self.http.request('POST', '/ws/api.dll',
            headers={'X-EBAY-API-IAF-TOKEN': self._access_token(), 'X-EBAY-API-CALL-NAME': call,
                     'X-EBAY-API-SITEID': '0', 'X-EBAY-API-COMPATIBILITY-LEVEL': '1477',
                     'Content-Type': 'text/xml; charset=utf-8'},
            body=f'<{call}Request xmlns="urn:ebay:apis:eBLBaseComponents">{field}</{call}Request>'.encode())
        try:
            if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
                raise ValueError()
            root = ET.fromstring(raw)
            if root.findtext('{*}Ack') not in ('Success', 'Warning'):
                raise ValueError()
            return root
        except Exception:
            raise PublicationError('READ_FAILED', 'Sandboxのアカウント確認に失敗しました。') from None

    def _identity(self):
        root = self._trading_read('GetUser')
        eias = root.findtext('{*}User/{*}EIASToken')
        user = root.findtext('{*}User/{*}UserID')
        if not eias or eias != setting('EBAY_SANDBOX_SELLER_EIAS') or user != setting('EBAY_SANDBOX_SELLER_USER_ID'):
            raise PublicationError('STALE', '認証されたSandbox sellerが設定と一致しません。')
        return sha256(eias.encode()).hexdigest()

    def _read(self, target, version):
        self.check_enabled()
        if (target.get('environment') != 'SANDBOX' or target.get('api_family') != 'INVENTORY'
                or target.get('offer_id') not in setting('EBAY_SANDBOX_ALLOWED_OFFER_IDS').split(',')
                or not re.fullmatch(r'[0-9]+', target.get('offer_id', ''))
                or not re.fullmatch(r'[0-9]+', target.get('external_listing_id', ''))
                or not isinstance(target.get('sku'), str) or not 1 <= len(target['sku']) <= 50
                or target['sku'] in ('.', '..') or any(ord(ch) < 32 for ch in target['sku'])):
            raise PublicationError('DISABLED', '許可済みSandboxテストOfferのみ操作できます。')
        seller = self._identity()
        if seller != target['seller_account']:
            raise PublicationError('STALE', '承認したsellerと一致しません。')
        offer = self._json('GET', 'offer/' + target['offer_id'])
        offers = self._json('GET', 'offer?' + urlencode({'sku': target['sku']}))
        inventory = self._json('GET', 'inventory_item/' + quote(target['sku'], safe=''))
        try:
            listing = offer.get('listing', {})
            published = offer['status'] == 'PUBLISHED'
            if (offers['total'] != 1 or len(offers['offers']) != 1
                    or offers['offers'][0]['offerId'] != target['offer_id']
                    or offer['offerId'] != target['offer_id'] or offer['sku'] != target['sku']
                    or offer['marketplaceId'] != target['marketplace'] or offer['format'] != 'FIXED_PRICE'
                    or offer.get('listingDuration') != 'GTC'
                    or inventory['sku'] != target['sku'] or inventory.get('inventoryItemGroupKeys')
                    or inventory.get('groupIds') or inventory.get('availability', {}).get('pickupAtLocationAvailability')
                    or offer.get('inventoryItemGroupKey')
                    or listing.get('listingOnHold')
                    or (published and (listing.get('listingId') != target['external_listing_id']
                                       or listing.get('listingStatus') != 'ACTIVE'))
                    or (not published and offer['status'] != 'UNPUBLISHED')
                    or (listing.get('listingId') and listing['listingId'] != target['external_listing_id'])):
                raise ValueError()
            ship = inventory['availability']['shipToLocationAvailability']
            if ship.get('availabilityDistributions') or ship.get('allocationByFormat', {}).get('auction', 0):
                raise ValueError()
            oq, iq = offer['availableQuantity'], ship['quantity']
            price = offer['pricingSummary']['price']
            currency = price['currency']
            amount = Decimal(price['value'])
            if (currency != target['currency'] or SITES.get(target['marketplace']) != currency
                    or type(oq) is not int or type(iq) is not int or min(oq, iq) < 0
                    or not amount.is_finite() or amount <= 0
                    or amount != amount.quantize(Decimal(1).scaleb(-PRICE_PLACES[currency]))):
                raise ValueError()
            values = {k: target[k] for k in IDENTIFIERS}
            values.update(sku=target['sku'], site=target['marketplace'], currency=currency,
                price=float(amount), quantity=min(oq, iq), offer_quantity=oq, inventory_quantity=iq)
            return dict(external_listing_id=target['external_listing_id'], payload=values,
                        status='ACTIVE' if published else 'ENDED', version=version)
        except (KeyError, TypeError, ValueError, ArithmeticError):
            raise PublicationError('STALE', '出品識別子・通貨・数量・単一Offer条件を確認できません。送信しません。') from None

    def get_listing(self, external_listing_id):
        self.check_enabled()
        if self.factory is None:
            raise PublicationError('DISABLED', 'Sandbox検証DBが必要です。')
        with self.factory() as c:
            row = c.execute('SELECT * FROM sandbox_marketplace_listings WHERE external_listing_id=?', (external_listing_id,)).fetchone()
        if row is None:
            raise PublicationError('INVALID', '検証用出品との明示的な紐付けが必要です。')
        return self._read(sandbox_binding(dict(row)), row['version'])

    def _apply(self, action, payload, key):
        self.check_enabled()
        if action not in SUPPORTED:
            raise PublicationError('DISABLED', 'このSandbox操作は未対応です。')
        # The provider itself also requires the claimed, immutable approval and Outbox.
        from .approval_service import payload_hash, validate_changes
        from .approval_repository import marketplace_record
        from .repositories import ProductRepository
        validate_changes(action, payload['changes'])
        with self.factory() as c:
            r = c.execute('SELECT * FROM sandbox_approval_requests WHERE idempotency_key=?', (key,)).fetchone()
            event = c.execute('SELECT * FROM outbox_events WHERE event_id=?', (r['outbox_event_id'],)).fetchone() if r else None
            if (not r or r['status'] != 'EXECUTING' or r['mode'] != 'SANDBOX'
                    or not r['approved_by'] or r['action_type'] != action
                    or r['approved_payload_json'] != encode(payload) or not event
                    or event['event_type'] != 'ebay.sandbox.approval.execute' or event['status'] != 'processing'
                    or event['aggregate_id'] != r['approval_request_id']
                    or json.loads(event['payload_json']) != {'approval_request_id': r['approval_request_id'],
                        'mode': 'SANDBOX', 'payload_hash': payload_hash(payload)}):
                raise PublicationError('DISABLED', '実行権を取得した承認済み要求のみ送信できます。')
            try:
                validate_local(marketplace_record(c, r['marketplace_listing_id'], sandbox=True),
                               ProductRepository(c).get(r['product_id']), dict(r), payload)
            except ValueError:
                raise PublicationError('STALE', '承認対象の紐付けが変わっています。送信しません。') from None
            prior = c.execute('SELECT * FROM sandbox_api_dispatches WHERE idempotency_key=?', (key,)).fetchone()
        if prior:
            raise PublicationError('UNKNOWN_RESULT', '送信意図が記録済みです。再送せず照合してください。', uncertain=True)
        validate_remote(payload, self.get_listing(payload['external_listing_id']))
        if action == 'END_LISTING' and payload.get('end_confirmed') is not True:
            raise PublicationError('INVALID', '出品終了の確認が必要です。')
        if payload['changes'].get('quantity') == 0:
            if self._trading_read('GetUserPreferences').findtext('{*}OutOfStockControlPreference') != 'true':
                raise PublicationError('INVALID', '在庫切れ継続設定を確認できません。数量0は送信しません。')
        target = payload['target']
        with self.factory() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('''INSERT INTO sandbox_api_dispatches
                (idempotency_key,approval_request_id,marketplace_listing_id,action_type,payload_hash,payload_json,state,created_at,updated_at)
                VALUES (?,?,?,?,?,?,'INTENT',?,?)''', (key, r['approval_request_id'], r['marketplace_listing_id'], action,
                    payload_hash(payload), encode(payload), utc_now(), utc_now()))
        try:
            if action == 'END_LISTING':
                response = self._json('POST', 'offer/' + target['offer_id'] + '/withdraw', write=True)
                if response.get('listingId') != target['external_listing_id']:
                    raise ValueError()
            else:
                offer = {'offerId': target['offer_id']}
                request = {'sku': target['sku'], 'offers': [offer]}
                if action == 'UPDATE_PRICE':
                    offer['price'] = {'value': str(payload['changes']['price']), 'currency': target['currency']}
                else:
                    offer['availableQuantity'] = payload['changes']['quantity']
                    request['shipToLocationAvailability'] = {'quantity': payload['changes']['quantity']}
                response = self._json('POST', 'bulk_update_price_quantity', body={'requests': [request]}, write=True)
                parts = response.get('responses', [])
                if (not parts or not any(p.get('offerId') == target['offer_id'] for p in parts)
                        or any(p.get('statusCode') != 200 or p.get('errors') or p.get('sku') != target['sku']
                               or p.get('offerId') not in (None, target['offer_id']) for p in parts)):
                    raise ValueError()
            return self.lookup_execution(key)
        except Exception:
            raise PublicationError('UNKNOWN_RESULT', '送信後の状態確認が必要です。自動再送は行いません。', uncertain=True) from None

    def lookup_execution(self, idempotency_key):
        self.check_enabled()
        with self.factory() as c:
            row = c.execute('SELECT * FROM sandbox_api_dispatches WHERE idempotency_key=?', (idempotency_key,)).fetchone()
        if row is None:
            return None
        payload = json.loads(row['payload_json'])
        result = self._read(payload['target'], payload['expected_revision'] + 1)
        validate_result(row['action_type'], payload, result)
        # Matching current state proves convergence, not that this request caused the change.
        with self.factory() as c:
            c.execute("UPDATE sandbox_api_dispatches SET state=CASE WHEN state='PROJECTED' THEN state ELSE 'CONFIRMED' END,result_json=?,updated_at=? WHERE idempotency_key=?",
                      (encode(result), utc_now(), idempotency_key))
        return result

    def update_price(self, payload, *, idempotency_key):
        return self._apply('UPDATE_PRICE', payload, idempotency_key)

    def update_quantity(self, payload, *, idempotency_key):
        return self._apply('UPDATE_QUANTITY', payload, idempotency_key)

    def end_listing(self, payload, *, idempotency_key):
        return self._apply('END_LISTING', payload, idempotency_key)

    def _disabled(self, *args, **kwargs):
        raise PublicationError('DISABLED', 'Sandbox新規出品・一括編集は未対応です。')

    create_listing = revise_listing = publish = _disabled
