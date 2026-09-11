"""Explicit approval -> publication -> atomic legacy registration. No worker/API calls."""

import json

from app_database import remote_database_is_configured
from .draft_repository import ListingDraftRepository, encode
from .migrations import utc_now
from .publication_provider import MockPublicationProvider, PublicationError, publication_provider
from .publication_repository import PublicationRepository
from .publication_validation import publication_inputs, validate_publication
from .repositories import AuditLogRepository, InventoryRepository, ProductRepository
from .services import ListingRegistrationService, available_quantity


def effective_status(draft, publication):
    return publication['status'] if publication else draft['status']


class PublicationService:
    def __init__(self, connection_factory, *, calculate_expected=None, provider=None, allow_mock=False):
        self.connection_factory = connection_factory
        self.calculate_expected = calculate_expected
        self.provider = provider
        self.allow_mock = allow_mock

    def get(self, draft_id):
        with self.connection_factory() as c:
            return PublicationRepository(c).get_for_draft(draft_id)

    def _provider(self):
        if not self.allow_mock or remote_database_is_configured():
            raise PublicationError('DISABLED', 'Mock公開は明示的に有効化したローカル検証DBのみで利用できます。本番DBでは実行できません。')
        provider = self.provider or publication_provider('MOCK')
        if not isinstance(provider, MockPublicationProvider) or provider.mode != 'MOCK':
            raise PublicationError('DISABLED', '本番・Sandboxへの外部API接続は未実装です。')
        return provider

    @staticmethod
    def _actor(actor):
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError('操作者名を入力してください。')
        return actor.strip()

    @staticmethod
    def _audit(c, record, action, actor, after):
        AuditLogRepository(c).append(entity_type='publication', entity_id=record['publication_id'],
            action='publication.' + action, actor_type='human', actor_id=actor,
            before=record, after=after,
            metadata={'product_id': record['product_id'], 'listing_draft_id': record['listing_draft_id'],
                      'idempotency_key': record['idempotency_key'], 'mode': record['mode']})

    @staticmethod
    def _public_payload(draft):
        p = publication_inputs(draft)
        # A future transport must not receive supplier URLs, costs, or generation prompts.
        payload = {key: draft[key] for key in ('title', 'description', 'category_id', 'condition_id',
                                                'site', 'currency', 'price', 'quantity')}
        payload['item_specifics'] = json.loads(draft['item_specifics_json'])
        payload.update({key: p.get(key) for key in ('sku', 'country_of_origin', 'hs_code', 'hts_code',
                                                   'weight_g', 'length_cm', 'width_cm', 'height_cm',
                                                   'shipping_carrier', 'shipping_service', 'buyer_shipping_usd')})
        return payload

    def _payload(self, c, draft):
        if self.calculate_expected is None:
            raise ValueError('既存の予定利益計算関数が接続されていません。公開は開始しません。')
        p = publication_inputs(draft)
        snapshot = json.loads(draft['generation_input_json']).get('selected_calculation', {})
        data = {key: value for key, value in snapshot.items() if key.startswith(('planned_', 'zonos_', 'cpass_', 'us_tariff_'))}
        now = utc_now()
        data.update(product_name=json.loads(draft['generation_input_json'])['product']['product_name'],
                    platform='eBay', status='出品中', listing_date=now[:10], created_at=now, updated_at=now,
                    listing_price=draft['price'], listing_price_usd=draft['price'], currency_code=draft['currency'],
                    sku=str(p['sku']).strip(), purchase_price=p['purchase_price'], purchase_price_yen=p['purchase_price'],
                    expected_shipping=p['shipping_yen'], international_shipping_yen=p['shipping_yen'],
                    planned_shipping_yen=p['shipping_yen'], expected_shipping_carrier=p['shipping_carrier'],
                    expected_shipping_service=p['shipping_service'], shipping_carrier=p['shipping_carrier'],
                    shipping_service=p['shipping_service'], shipping_weight_g=p['weight_g'],
                    package_weight_g=p['weight_g'], package_length_cm=p['length_cm'],
                    package_width_cm=p['width_cm'], package_height_cm=p['height_cm'],
                    country_of_origin=p['country_of_origin'], hts_code=p.get('hts_code') or '',
                    source_url=p.get('source_url') or '', shipping_breakdown_json=p['shipping_breakdown_json'] or '',
                    platform_memo='[MOCK公開検証・実出品ではありません] ' + draft['listing_draft_id'])
        for key in ('exchange_rate', 'usd_jpy_rate', 'buyer_shipping_usd', 'domestic_shipping_yen',
                    'packaging_yen', 'other_cost_yen', 'ebay_fee_rate', 'promoted_listing_rate',
                    'exchange_spread_rate', 'fixed_fee_usd'):
            data[key] = p.get(key) or 0
        data.update(self.calculate_expected(data))
        data['planned_profit_margin'] = data['profit_margin']
        schema = {row[1]: row for row in c.execute('PRAGMA table_info(listings)')}
        columns = set(schema)
        if not {'product_id', 'shipping_breakdown_json', 'product_name', 'platform', 'status'} <= columns:
            raise ValueError('出品管理テーブルが未準備です。公開は開始しません。')
        return {key: value for key, value in data.items() if key in columns and
                (value is not None or not schema[key][3])}

    def publish(self, draft_id, *, actor_id):
        actor_id = self._actor(actor_id)
        provider = self._provider()
        with self.connection_factory() as c:
            c.execute('BEGIN IMMEDIATE')
            repo = PublicationRepository(c)
            record = repo.get_for_draft(draft_id)
            if not record:
                raise ValueError('第5段階の検証を通過した承認済み版がありません。編集・レビュー・承認してください。')
            if record['status'] == 'PUBLISHED':
                return record
            if record['status'] == 'PUBLISHING' or record['reconcile_required']:
                raise ValueError('公開結果の照合が必要です。再送せず「公開結果を照合」を実行してください。')
            if record['status'] not in ('APPROVED', 'FAILED'):
                raise ValueError('承認済みまたは失敗状態のみ公開できます。')
            draft = ListingDraftRepository(c).get(draft_id)
            if draft['status'] != 'APPROVED' or draft['revision'] != record['approved_revision']:
                raise ValueError('承認した版から変更されています。再承認してください。')
            product = ProductRepository(c).get(record['product_id'])
            inventory = InventoryRepository(c).get(record['product_id'])
            if not product or str(product['status']).upper() == 'ARCHIVED' or inventory is None:
                raise ValueError('商品または在庫の状態を確認してください。')
            available = available_quantity(inventory)
            if available is not None and record['quantity'] > available:
                raise ValueError('現在の利用可能在庫が不足しています。')
            frozen = json.loads(record['approved_snapshot_json'])
            validate_publication(c, frozen)
            payload = json.loads(record['listing_payload_json']) if record['listing_payload_json'] else self._payload(c, frozen)
            update = dict(status='PUBLISHING', attempt_count=record['attempt_count'] + 1,
                          listing_payload_json=encode(payload), updated_at=utc_now(), reconcile_required=1)
            repo.update(record['publication_id'], **update)
            self._audit(c, record, 'started', actor_id, update)
            record.update(update)
        try:
            receipt = provider.publish(self._public_payload(frozen), idempotency_key=record['idempotency_key'])
        except Exception as exc:
            self._fail(record, actor_id, exc)
            return self.get(draft_id)
        # If local persistence fails after a provider success, leave PUBLISHING.
        # A subsequent explicit reconciliation retrieves the same receipt, never re-sends.
        return self._finish(record, receipt, actor_id)

    def _fail(self, record, actor, error):
        known = isinstance(error, PublicationError)
        update = dict(status='FAILED', error_code=error.code if known else 'UNKNOWN_RESULT',
                      error_message=str(error)[:500] if known else '公開結果を確定できません。安全のため再送せず照合してください。',
                      failed_at=utc_now(), updated_at=utc_now(),
                      reconcile_required=int(error.uncertain if known else True))
        with self.connection_factory() as c:
            c.execute('BEGIN IMMEDIATE')
            current = PublicationRepository(c).get_for_draft(record['listing_draft_id'])
            if current['status'] != 'PUBLISHING' or current['attempt_count'] != record['attempt_count']:
                return
            PublicationRepository(c).update(record['publication_id'], **update)
            self._audit(c, current, 'failed', actor, update)

    def reconcile(self, draft_id, *, actor_id):
        actor_id = self._actor(actor_id)
        provider = self._provider()
        record = self.get(draft_id)
        if not record or record['status'] not in ('PUBLISHING', 'FAILED') or not record['reconcile_required']:
            raise ValueError('公開中または失敗した処理のみ照合できます。')
        try:
            receipt = provider.lookup(record['idempotency_key'])
        except Exception:
            raise ValueError('照合できませんでした。再送していません。') from None
        if receipt is None:
            raise ValueError('公開結果を確認できません。自動再送は行いません。')
        return self._finish(record, receipt, actor_id)

    def _finish(self, record, receipt, actor):
        if not receipt.item_id.startswith('MOCK-') or receipt.listing_url:
            raise ValueError('Mock以外の公開結果は受け入れません。')
        with self.connection_factory() as c:
            c.execute('BEGIN IMMEDIATE')
            repo = PublicationRepository(c)
            current = repo.get_for_draft(record['listing_draft_id'])
            if current['status'] == 'PUBLISHED':
                return current
            if current['status'] not in ('PUBLISHING', 'FAILED') or not current['listing_payload_json']:
                raise ValueError('公開結果を保存できない状態です。')
            payload = json.loads(current['listing_payload_json'])
            registration = ListingRegistrationService(self.connection_factory).register(
                listing_data=payload, product_name=payload['product_name'], platform='eBay',
                sku=current['sku'], product_id=current['product_id'], actor_id=actor,
                connection=c, audit_metadata={'source': 'publication', 'mode': 'MOCK',
                    'listing_draft_id': current['listing_draft_id'], 'ebay_item_id': receipt.item_id})
            update = dict(status='PUBLISHED', ebay_item_id=receipt.item_id, listing_url=receipt.listing_url,
                          listing_id=registration.listing_id, published_at=utc_now(), updated_at=utc_now(),
                          reconcile_required=0, error_code=None, error_message=None)
            repo.update(current['publication_id'], **update)
            self._audit(c, current, 'succeeded', actor, update)
            return repo.get_for_draft(current['listing_draft_id'])
