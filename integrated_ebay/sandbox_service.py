"""Reuse the human approval/Outbox state machine with isolated Sandbox records."""

import json
from hashlib import sha256
from uuid import uuid4

from app_database import remote_database_is_configured
from .approval_repository import ApprovalRepository, marketplace_record
from .approval_service import ApprovalService
from .change_safety import validate_result
from .draft_repository import encode
from .migrations import utc_now
from .publication_provider import PublicationError
from .repositories import ProductRepository, AuditLogRepository
from .sandbox_http import setting
from .sandbox_inventory import SandboxInventoryProvider, SUPPORTED, SITES


class SandboxApprovalService(ApprovalService):
    request_table = 'sandbox_approval_requests'
    attempt_table = 'sandbox_approval_attempts'
    listing_table = 'sandbox_marketplace_listings'
    event_type = 'ebay.sandbox.approval.execute'

    def __init__(self, factory, *, provider=None):
        super().__init__(factory, mode='SANDBOX', provider=provider or SandboxInventoryProvider(factory))

    def _local(self):
        if (self.mode != 'SANDBOX' or type(self.provider) is not SandboxInventoryProvider
                or remote_database_is_configured()):
            raise PublicationError('DISABLED', 'Sandboxは明示的なローカル検証DBのみ使用できます。本番DBは変更しません。')
        self.provider.check_enabled()

    def _repo(self, c):
        return ApprovalRepository(c, sandbox=True)

    def _listing(self, c, key):
        return marketplace_record(c, key, sandbox=True)

    def propose_create(self, *args, **kwargs):
        raise PublicationError('DISABLED', 'Sandbox新規出品は今回の対象外です。')

    def propose_change(self, marketplace_id, action, changes, **kwargs):
        if action not in SUPPORTED:
            raise PublicationError('DISABLED', 'Sandboxでは価格・数量・明示的終了のみ対応しています。')
        return super().propose_change(marketplace_id, action, changes, **kwargs)

    def bind_existing_test_offer(self, product_id, *, offer_id, item_id, sku, marketplace, currency,
                                 actor_id, test_target_confirmed=False):
        """Explicit read-only remote import; never backfill normal listings/products."""
        self._local()
        actor = self._actor(actor_id, human=True)
        if test_target_confirmed is not True or SITES.get(marketplace) != currency:
            raise ValueError('Sandbox検証専用出品の明示確認・対応通貨が必要です。')
        target = dict(environment='SANDBOX', api_family='INVENTORY', offer_id=offer_id,
            external_listing_id=item_id, sku=sku, marketplace=marketplace, currency=currency,
            seller_account=sha256(setting('EBAY_SANDBOX_SELLER_EIAS').encode()).hexdigest())
        remote = self.provider._read(target, 1)
        if remote['status'] != 'ACTIVE':
            raise ValueError('有効な検証専用出品のみ紐付けできます。')
        key, now = 'sbl_' + str(uuid4()), utc_now()
        with self.factory() as c:
            c.execute('BEGIN IMMEDIATE')
            product = ProductRepository(c).get(product_id)
            if not product or product['status'].upper() == 'ARCHIVED':
                raise ValueError('有効な検証商品が必要です。')
            if c.execute('SELECT 1 FROM sandbox_marketplace_listings WHERE external_listing_id=? OR sku=?', (item_id, sku)).fetchone():
                raise ValueError('このSandbox Item/SKUは既に紐付いています。上書きしません。')
            c.execute('''INSERT INTO sandbox_marketplace_listings
                (marketplace_listing_id,product_id,external_listing_id,sku,marketplace,mode,status,
                 current_payload_json,binding_json,version,published_at,updated_at)
                VALUES (?,?,?,?,?,'SANDBOX','ACTIVE',?,?,1,?,?)''',
                (key, product_id, item_id, sku, marketplace, encode(remote['payload']), encode(target), now, now))
            AuditLogRepository(c).append(entity_type='sandbox_binding', entity_id=key,
                action='sandbox.binding.verified', actor_type='human', actor_id=actor,
                after={'product_id': product_id, 'target': target})
        return key

    def _claim_target(self, c, r):
        if c.execute('''SELECT 1 FROM sandbox_approval_requests WHERE marketplace_listing_id=?
            AND approval_request_id!=? AND (status='EXECUTING' OR reconcile_required=1)''',
            (r['marketplace_listing_id'], r['approval_request_id'])).fetchone() or c.execute('''
            SELECT 1 FROM sandbox_api_dispatches WHERE marketplace_listing_id=? AND state!='PROJECTED' ''',
            (r['marketplace_listing_id'],)).fetchone():
            raise ValueError('同じSandbox出品に未確定の実行があります。再送せず照合してください。')

    def refresh_test_offer(self, marketplace_id, *, actor_id, refresh_confirmed=False):
        self._local()
        actor = self._actor(actor_id, human=True)
        if refresh_confirmed is not True:
            raise ValueError('再提案用の現在値取得を確認してください。')
        with self.factory() as c:
            before = self._listing(c, marketplace_id)
        if not before:
            raise ValueError('Sandbox出品がありません。')
        remote = self.provider.get_listing(before['external_listing_id'])
        with self.factory() as c:
            c.execute('BEGIN IMMEDIATE')
            current = self._listing(c, marketplace_id)
            if current != before or c.execute('''SELECT 1 FROM sandbox_approval_requests
                WHERE marketplace_listing_id=? AND (status IN ('PENDING','APPROVED','EXECUTING') OR reconcile_required=1)''',
                (marketplace_id,)).fetchone() or c.execute('''SELECT 1 FROM sandbox_api_dispatches
                WHERE marketplace_listing_id=? AND state!='PROJECTED' ''', (marketplace_id,)).fetchone():
                raise ValueError('未確定の実行は先に照合してください。未実行の提案は取り消してから現在値を取得してください。')
            c.execute('''UPDATE sandbox_marketplace_listings SET current_payload_json=?,status=?,version=version+1,
                updated_at=? WHERE marketplace_listing_id=?''',
                (encode(remote['payload']), remote['status'], utc_now(), marketplace_id))
            AuditLogRepository(c).append(entity_type='sandbox_binding', entity_id=marketplace_id,
                action='sandbox.snapshot.refreshed', actor_type='human', actor_id=actor,
                before=before, after=self._listing(c, marketplace_id))
            return self._listing(c, marketplace_id)

    def _verify_change_result(self, r, result):
        payload = json.loads(r['approved_payload_json'])
        validate_result(r['action_type'], payload, result)
        remote = self.provider.get_listing(result['external_listing_id'])
        # This is our DB projection revision, not an eBay ETag or remote CAS token.
        remote['version'] = result['version']
        if remote != result:
            raise PublicationError('UNKNOWN_RESULT', '再取得したSandbox状態が期待値と一致しません。', uncertain=True)

    def _save_sandbox_result(self, c, current, result):
        payload = json.loads(current['approved_payload_json'])
        self._current(c, current, payload)
        validate_result(current['action_type'], payload, result)
        intent = c.execute('SELECT * FROM sandbox_api_dispatches WHERE idempotency_key=?', (current['idempotency_key'],)).fetchone()
        if not intent or intent['state'] != 'CONFIRMED' or intent['result_json'] != encode(result):
            raise ValueError('Sandboxの再取得結果が未確認です。')
        c.execute('''UPDATE sandbox_marketplace_listings SET current_payload_json=?,status=?,version=?,updated_at=?,
            approval_request_id=? WHERE marketplace_listing_id=?''', (encode(result['payload']), result['status'],
            result['version'], utc_now(), current['approval_request_id'], current['marketplace_listing_id']))
        c.execute("UPDATE sandbox_api_dispatches SET state='PROJECTED',updated_at=? WHERE idempotency_key=?",
                  (utc_now(), current['idempotency_key']))
        return result['external_listing_id']
