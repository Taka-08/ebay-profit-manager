"""Fail-closed checks shared by approval, Mock dispatch and reconciliation.

These limits describe this application's supported inputs, not eBay-wide limits.
Real listing bindings and carrier/API-specific policy remain disabled.
"""

import json
from decimal import Decimal, InvalidOperation

from .publication_provider import PublicationError


MAX_QUANTITY = 2_147_483_647
PRICE_PLACES = {'USD': 2, 'CAD': 2, 'GBP': 2, 'AUD': 2, 'EUR': 2, 'JPY': 0}
BINDING_FIELDS = ('marketplace_listing_id', 'product_id', 'listing_draft_id',
                  'publication_id', 'external_listing_id', 'sku', 'marketplace', 'mode')


def binding(listing):
    if listing.get('mode') == 'SANDBOX':
        from .sandbox_inventory import sandbox_binding
        return sandbox_binding(listing)
    target = {key: listing[key] for key in BINDING_FIELDS}
    before = json.loads(listing['current_payload_json'])
    target['currency'] = before.get('currency')
    if (any(not isinstance(value, str) or not value.strip() for value in target.values())
            or target['mode'] != 'MOCK' or not target['external_listing_id'].startswith('MOCK-')
            or before.get('sku') != target['sku'] or before.get('site') != target['marketplace']
            or target['currency'] not in PRICE_PLACES):
        raise ValueError('商品・SKU・Marketplace・通貨の対応を確認できません。送信しません。')
    return target


def validate_change_values(payload):
    target = payload.get('target')
    if not isinstance(target, dict) or target.get('currency') not in PRICE_PLACES:
        raise ValueError('対象情報のない旧提案です。取り消して再提案してください。')
    changes = payload['changes']
    if 'price' in changes:
        price = Decimal(str(changes['price']))
        quantum = Decimal(1).scaleb(-PRICE_PLACES[target['currency']])
        try:
            valid = price.is_finite() and price > 0 and price == price.quantize(quantum)
        except InvalidOperation:
            valid = False
        if not valid:
            raise ValueError('価格の小数桁が対象通貨と一致しません。')
    if 'quantity' in changes:
        quantity = changes['quantity']
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 0 <= quantity <= MAX_QUANTITY:
            raise ValueError('数量は0以上の対応範囲内の整数にしてください。NULLは数量0ではありません。')


def validate_local(listing, product, request, payload):
    if not listing or not product or str(product['status']).upper() == 'ARCHIVED':
        raise ValueError('有効な商品と出品の対応を確認できません。')
    target = binding(listing)
    if (payload.get('target') != target or product['product_id'] != target['product_id']
            or 'product_sku' not in payload or product['sku'] != payload['product_sku']
            or any(request[key] != target[key] for key in
                   ('product_id', 'listing_draft_id', 'publication_id', 'marketplace_listing_id'))
            or payload.get('external_listing_id') != target['external_listing_id']):
        raise ValueError('承認した対象と現在の商品・出品の識別子が一致しません。')
    if (listing['status'] != 'ACTIVE' or listing['version'] != payload.get('expected_revision')
            or json.loads(listing['current_payload_json']) != payload.get('expected_before')
            or json.loads(request['before_payload_json']) != payload.get('expected_before')):
        raise ValueError('出品の現在値が提案時から変更されています。')
    validate_change_values(payload)


def validate_remote(payload, remote):
    """Also run under the Mock transaction lock to close the preflight/write race."""
    before = payload.get('expected_before')
    target = payload.get('target', {})
    if (not isinstance(before, dict) or not target or not isinstance(remote, dict)
            or remote.get('external_listing_id') != payload.get('external_listing_id')
            or remote.get('external_listing_id') != target.get('external_listing_id')
            or before.get('sku') != target.get('sku') or before.get('site') != target.get('marketplace')
            or before.get('currency') != target.get('currency')
            or remote.get('status') != 'ACTIVE' or remote.get('version') != payload.get('expected_revision')
            or remote.get('payload') != before):
        raise PublicationError('STALE', '出品先の識別子・通貨・現在値が承認版と一致しません。送信していません。')
    validate_change_values(payload)


def validate_result(action, payload, result):
    expected = dict(payload['expected_before'])
    expected.update(payload['changes'])
    if payload.get('target', {}).get('mode') == 'SANDBOX' and 'quantity' in payload['changes']:
        expected['inventory_quantity'] = expected['offer_quantity'] = payload['changes']['quantity']
    if (not isinstance(result, dict) or result.get('external_listing_id') != payload['external_listing_id']
            or result.get('payload') != expected or result.get('version') != payload['expected_revision'] + 1
            or result.get('status') != ('ENDED' if action == 'END_LISTING' else 'ACTIVE')):
        raise PublicationError('UNKNOWN_RESULT', '返却結果が承認した変更と一致しません。再送せず照合してください。', uncertain=True)
