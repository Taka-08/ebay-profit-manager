"""Proposal -> human approval -> Outbox -> isolated no-network Mock execution."""

import json
import math
from hashlib import sha256

from .approval_repository import ApprovalRepository, marketplace_record
from .change_safety import binding, validate_change_values, validate_local, validate_remote, validate_result
from .draft_repository import ListingDraftRepository, encode
from .ebay_api import MockEbayProvider, execution_mode, require_mock_execution
from .ids import generate_entity_id
from .migrations import utc_now
from .publication_provider import PublicationError
from .publication_repository import PublicationRepository
from .publication_service import PublicationService
from .publication_validation import validate_publication
from .repositories import AuditLogRepository, InventoryRepository, OutboxRepository, ProductRepository
from .services import available_quantity


ACTIONS = ('CREATE_LISTING', 'UPDATE_PRICE', 'UPDATE_QUANTITY', 'END_LISTING', 'REVISE_LISTING')
STATUSES = ('PENDING', 'APPROVED', 'REJECTED', 'EXECUTING', 'SUCCEEDED', 'FAILED', 'CANCELLED')
EVENT_TYPE = 'ebay.approval.execute'


def payload_hash(payload):
    return sha256(encode(payload).encode()).hexdigest()


def validate_changes(action, changes):
    allowed = {'UPDATE_PRICE': {'price'}, 'UPDATE_QUANTITY': {'quantity'},
               'END_LISTING': set(), 'REVISE_LISTING': {'title', 'description', 'price', 'quantity'}}
    if action not in allowed or not isinstance(changes, dict) or set(changes) - allowed[action]:
        raise ValueError('このアクションでは変更できない項目があります。')
    if action != 'END_LISTING' and not changes:
        raise ValueError('変更内容を入力してください。')
    for key, value in changes.items():
        if key == 'price' and (isinstance(value, bool) or not isinstance(value, (int, float)) or
                               not math.isfinite(value) or value <= 0):
            raise ValueError('新価格は0より大きい有限数にしてください。')
        if key == 'quantity' and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise ValueError('新数量は0以上の整数にしてください。')
        if key in ('title', 'description') and (not isinstance(value, str) or not value.strip() or
                                               len(value) > (80 if key == 'title' else 50000)):
            raise ValueError('タイトルまたは説明文の長さが不正です。')
    return changes


class ApprovalService:
    def __init__(self, factory, *, calculate_expected=None, mode=None, provider=None):
        self.factory = factory
        self.calculate_expected = calculate_expected
        self.mode = mode or execution_mode()
        self.provider = provider or MockEbayProvider(factory)

    def _local(self):
        require_mock_execution(self.mode)
        if type(self.provider) is not MockEbayProvider or self.provider.mode != 'MOCK':
            raise ValueError('今回はMock Provider以外を実行できません。')

    @staticmethod
    def _actor(actor_id, actor_type='human', *, human=False):
        if actor_type not in ('human', 'ai', 'system') or (human and actor_type != 'human'):
            raise ValueError('承認操作は人間に限定されています。')
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise ValueError('操作者名を入力してください。')
        return actor_id.strip()

    @staticmethod
    def _audit(c, record, action, actor, actor_type='human', before=None):
        AuditLogRepository(c).append(entity_type='approval_request', entity_id=record['approval_request_id'],
            action=action, actor_type=actor_type, actor_id=actor, before=before, after=record,
            metadata={'product_id': record['product_id'], 'mode': record['mode']})

    @staticmethod
    def _version(r, expected):
        if not r or r['version'] != expected:
            raise ValueError('別の操作で更新されています。最新状態を確認してください。')

    def get(self, request_id):
        with self.factory() as c:
            return ApprovalRepository(c).get(request_id)

    def list(self):
        with self.factory() as c:
            return ApprovalRepository(c).list()

    def history(self, request_id):
        with self.factory() as c:
            return ApprovalRepository(c).attempts(request_id)

    def listings(self):
        with self.factory() as c:
            return [dict(r) for r in c.execute('''SELECT m.*,p.product_name FROM marketplace_listings m
                JOIN products p ON p.product_id=m.product_id ORDER BY m.updated_at DESC''')]

    def _insert(self, c, *, product_id, draft_id, publication_id, marketplace_id, action, payload,
                before, reason, source_status, actor, actor_type, key):
        if not isinstance(reason, str) or not reason.strip() or not isinstance(key, str) or not key.strip():
            raise ValueError('変更理由と冪等キーが必要です。')
        key = key.strip()
        product = ProductRepository(c).get(product_id)
        if not product or str(product['status']).upper() == 'ARCHIVED':
            raise ValueError('商品が見つからないかアーカイブ済みです。')
        previous = c.execute('SELECT * FROM approval_requests WHERE idempotency_key=?', (key,)).fetchone()
        if previous:
            if (previous['product_id'], previous['action_type'], previous['mode'], previous['proposed_payload_json'],
                previous['reason'], previous['marketplace_listing_id'], previous['publication_id']) != (
                    product_id, action, self.mode, encode(payload), reason.strip(), marketplace_id, publication_id):
                raise ValueError('同じ冪等キーの提案内容が異なります。')
            return dict(previous)
        if action == 'CREATE_LISTING' and c.execute('''SELECT 1 FROM approval_requests WHERE product_id=? AND mode=?
            AND action_type='CREATE_LISTING' AND status NOT IN ('REJECTED','CANCELLED')''', (product_id, self.mode)).fetchone():
            raise ValueError('この商品にはすでに新規出品の承認要求があります。')
        if marketplace_id:
            duplicate = c.execute('''SELECT * FROM approval_requests WHERE marketplace_listing_id=?
                AND mode=? AND action_type=? AND proposed_payload_json=?
                AND status NOT IN ('REJECTED','CANCELLED') ORDER BY created_at LIMIT 1''',
                (marketplace_id, self.mode, action, encode(payload))).fetchone()
            if duplicate:
                return dict(duplicate)
        now = utc_now()
        values = dict(approval_request_id=generate_entity_id('approval_request'), product_id=product_id,
            listing_draft_id=draft_id, publication_id=publication_id, marketplace_listing_id=marketplace_id,
            action_type=action, mode=self.mode, status='PENDING', proposed_payload_json=encode(payload),
            before_payload_json=encode(before), reason=reason.strip(), source_status=str(source_status),
            created_by=actor, created_actor_type=actor_type, created_at=now, updated_at=now, idempotency_key=key)
        repo = ApprovalRepository(c)
        repo.insert(values)
        result = repo.get(values['approval_request_id'])
        self._audit(c, result, 'proposal.created', actor, actor_type)
        return result

    def propose_create(self, draft_id, *, actor_id, idempotency_key, reason='承認済み下書きのMock公開', actor_type='human'):
        self._local()
        actor = self._actor(actor_id, actor_type)
        with self.factory() as c:
            c.execute('BEGIN IMMEDIATE')
            publication = PublicationRepository(c).get_for_draft(draft_id)
            if not publication or publication['status'] != 'APPROVED':
                raise ValueError('AI出品画面で内容をレビュー・承認した下書きを選んでください。')
            frozen = json.loads(publication['approved_snapshot_json'])
            return self._insert(c, product_id=publication['product_id'], draft_id=draft_id,
                publication_id=publication['publication_id'], marketplace_id=None, action='CREATE_LISTING',
                payload=PublicationService._public_payload(frozen), before={}, reason=reason, source_status='',
                actor=actor, actor_type=actor_type, key=idempotency_key)

    def propose_change(self, marketplace_id, action, changes, *, reason, actor_id, idempotency_key,
                       actor_type='human', source_status=''):
        self._local()
        actor = self._actor(actor_id, actor_type)
        validate_changes(action, changes)
        with self.factory() as c:
            c.execute('BEGIN IMMEDIATE')
            listing = marketplace_record(c, marketplace_id)
            if not listing or listing['mode'] != 'MOCK' or listing['status'] != 'ACTIVE':
                raise ValueError('第6段階で紐付いた有効なMock出品を選択してください。')
            payload = dict(external_listing_id=listing['external_listing_id'], expected_revision=listing['version'], changes=changes)
            payload.update(target=binding(listing), expected_before=json.loads(listing['current_payload_json']))
            product = ProductRepository(c).get(listing['product_id'])
            if not product:
                raise ValueError('紐付く商品がありません。')
            # Product SKU is optional; the approved listing may intentionally use another SKU.
            payload['product_sku'] = product['sku']
            validate_change_values(payload)
            if action == 'END_LISTING':
                payload['end_reason'] = reason.strip()
            return self._insert(c, product_id=listing['product_id'], draft_id=listing['listing_draft_id'],
                publication_id=listing['publication_id'], marketplace_id=marketplace_id, action=action,
                payload=payload, before=json.loads(listing['current_payload_json']), reason=reason,
                source_status=source_status, actor=actor, actor_type=actor_type, key=idempotency_key)

    def _current(self, c, r, payload):
        if r['action_type'] == 'CREATE_LISTING':
            publication = PublicationRepository(c).get_for_draft(r['listing_draft_id'])
            if not publication or publication['publication_id'] != r['publication_id']:
                raise ValueError('下書きの承認版が変更されました。再提案してください。')
            draft = ListingDraftRepository(c).get(r['listing_draft_id'])
            if (publication['status'] != 'APPROVED' or not draft or draft['status'] != 'APPROVED'
                    or draft['revision'] != publication['approved_revision']):
                raise ValueError('承認した版から変更されています。再承認してください。')
            frozen = json.loads(publication['approved_snapshot_json'])
            if PublicationService._public_payload(frozen) != payload:
                raise ValueError('承認済みpayloadと下書きの固定版が一致しません。')
            product = ProductRepository(c).get(r['product_id'])
            inventory = InventoryRepository(c).get(r['product_id'])
            if not product or str(product['status']).upper() == 'ARCHIVED' or inventory is None:
                raise ValueError('商品または在庫の状態を確認してください。')
            available = available_quantity(inventory)
            if available is not None and publication['quantity'] > available:
                raise ValueError('現在の利用可能在庫が不足しています。')
            validate_publication(c, frozen)
            return publication
        listing = marketplace_record(c, r['marketplace_listing_id'])
        if not listing or listing['status'] != 'ACTIVE' or listing['version'] != payload['expected_revision']:
            raise ValueError('現在値が提案時から変わりました。再提案してください。')
        if listing['external_listing_id'] != payload['external_listing_id']:
            raise ValueError('送信先IDが一致しません。')
        validate_local(listing, ProductRepository(c).get(r['product_id']), r, payload)
        return listing

    def _validate_before_send(self, r, payload):
        try:
            with self.factory() as c:
                self._current(c, r, payload)
        except ValueError as exc:
            # Nothing was dispatched, so this is safe to cancel/re-propose.
            code = 'APPROVAL_MISMATCH' if r['action_type'] == 'CREATE_LISTING' else 'STALE'
            raise PublicationError(code, '承認時から対象の版が変更されています。') from exc
        if r['action_type'] != 'CREATE_LISTING':
            # No write has been dispatched: failed reads may be retried, not reconciled as writes.
            try:
                remote = self.provider.get_listing(payload['external_listing_id'])
            except Exception as exc:
                raise PublicationError('READ_FAILED', '実行前の現在値取得に失敗しました。送信していません。') from exc
            validate_remote(payload, remote)

    def edit(self, request_id, changes, *, reason, expected_version, actor_id, actor_type='human'):
        self._local()
        actor = self._actor(actor_id, actor_type, human=True)
        with self.factory() as c:
            c.execute('BEGIN IMMEDIATE')
            repo = ApprovalRepository(c)
            r = repo.get(request_id)
            self._version(r, expected_version)
            if r['status'] != 'PENDING' or r['action_type'] == 'CREATE_LISTING':
                raise ValueError('PENDINGの変更提案のみ編集できます。新規出品は元の下書きで編集・再承認してください。')
            validate_changes(r['action_type'], changes)
            if not reason.strip():
                raise ValueError('変更理由が必要です。')
            payload = json.loads(r['proposed_payload_json'])
            payload['changes'] = changes
            if r['action_type'] == 'END_LISTING':
                payload['end_reason'] = reason.strip()
            validate_change_values(payload)
            repo.update(request_id, proposed_payload_json=encode(payload), reason=reason.strip(),
                        version=r['version'] + 1, updated_at=utc_now())
            result = repo.get(request_id)
            self._audit(c, result, 'approval.edited', actor, before=r)
            return result

    def approve(self, request_id, *, expected_version, actor_id, reviewed=False, end_confirmed=False, actor_type='human'):
        self._local()
        actor = self._actor(actor_id, actor_type, human=True)
        if not reviewed:
            raise ValueError('人間による内容確認が必要です。')
        with self.factory() as c:
            c.execute('BEGIN IMMEDIATE')
            repo = ApprovalRepository(c)
            r = repo.get(request_id)
            if r and r['status'] in ('APPROVED','EXECUTING','SUCCEEDED','FAILED'):
                return r
            self._version(r, expected_version)
            if r['status'] != 'PENDING':
                raise ValueError('承認待ちの提案のみ承認できます。')
            payload = json.loads(r['proposed_payload_json'])
            if r['mode'] != self.mode:
                raise ValueError('提案と現在の実行モードが一致しません。')
            if r['action_type'] != 'CREATE_LISTING':
                validate_changes(r['action_type'], payload['changes'])
            self._current(c, r, payload)
            if r['action_type'] == 'END_LISTING':
                if not end_confirmed:
                    raise ValueError('出品終了の最終確認が必要です。')
                payload['end_confirmed'] = True
            event = OutboxRepository(c).enqueue(event_type=EVENT_TYPE, aggregate_type='approval_request',
                aggregate_id=request_id, payload={'approval_request_id': request_id, 'mode': r['mode'],
                                                 'payload_hash': payload_hash(payload)},
                idempotency_key='ebay.execute:' + r['idempotency_key'])
            repo.update(request_id, status='APPROVED', approved_payload_json=encode(payload), approved_by=actor,
                approved_at=utc_now(), updated_at=utc_now(), execution_status='QUEUED',
                outbox_event_id=event.event_id, version=r['version'] + 1)
            result = repo.get(request_id)
            self._audit(c, result, 'approval.approved', actor, before=r)
            self._audit(c, result, 'ebay.execution.queued', actor)
            return result

    def reject(self, request_id, *, expected_version, actor_id, actor_type='human'):
        return self._stop(request_id, 'REJECTED', expected_version, actor_id, actor_type)

    def cancel(self, request_id, *, expected_version, actor_id, actor_type='human'):
        return self._stop(request_id, 'CANCELLED', expected_version, actor_id, actor_type)

    def _stop(self, request_id, status, version, actor, actor_type):
        self._local()
        actor = self._actor(actor, actor_type, human=True)
        with self.factory() as c:
            c.execute('BEGIN IMMEDIATE')
            repo = ApprovalRepository(c)
            r = repo.get(request_id)
            self._version(r, version)
            allowed = ('PENDING',) if status == 'REJECTED' else ('PENDING','APPROVED','FAILED')
            if r['status'] not in allowed or r['reconcile_required']:
                raise ValueError('この状態では却下・取り消しできません。')
            repo.update(request_id, status=status, execution_status=status, version=r['version'] + 1, updated_at=utc_now())
            if r['outbox_event_id']:
                c.execute("UPDATE outbox_events SET status='cancelled',updated_at=? WHERE event_id=?", (utc_now(), r['outbox_event_id']))
            result = repo.get(request_id)
            self._audit(c, result, 'approval.rejected' if status == 'REJECTED' else 'approval.cancelled', actor, before=r)
            return result

    def execute(self, request_id, *, actor_id):
        self._local()
        actor = self._actor(actor_id)
        with self.factory() as c:
            c.execute('BEGIN IMMEDIATE')
            repo = ApprovalRepository(c)
            r = repo.get(request_id)
            if not r or r['mode'] != self.mode:
                raise ValueError('承認要求または実行モードが一致しません。')
            if r['status'] == 'SUCCEEDED':
                return r
            if r['status'] == 'EXECUTING' or r['reconcile_required']:
                raise ValueError('結果の照合が必要です。再送は行いません。')
            if r['status'] not in ('APPROVED','FAILED') or not r['approved_payload_json']:
                raise ValueError('承認前・却下・取消済みの処理は実行できません。')
            payload = json.loads(r['approved_payload_json'])
            event = c.execute('SELECT * FROM outbox_events WHERE event_id=?', (r['outbox_event_id'],)).fetchone()
            expected = {'approval_request_id': request_id, 'mode': r['mode'], 'payload_hash': payload_hash(payload)}
            if not event or event['event_type'] != EVENT_TYPE or event['aggregate_id'] != request_id or json.loads(event['payload_json']) != expected:
                raise ValueError('承認済みキューの照合に失敗しました。送信しません。')
            if r['action_type'] == 'END_LISTING' and payload.get('end_confirmed') is not True:
                raise ValueError('出品終了の最終確認がありません。')
            now = utc_now()
            repo.update(request_id, status='EXECUTING', execution_status='RUNNING', reconcile_required=1,
                        attempt_count=r['attempt_count'] + 1, last_attempt_at=now, version=r['version'] + 1, updated_at=now)
            c.execute("UPDATE outbox_events SET status='processing',attempt_count=attempt_count+1,updated_at=? WHERE event_id=?", (now, r['outbox_event_id']))
            r = repo.get(request_id)
            c.execute('''INSERT INTO approval_execution_attempts
                (approval_request_id,attempt_number,status,started_at,actor_id) VALUES (?,?,'STARTED',?,?)''',
                (request_id, r['attempt_count'], now, actor))
            self._audit(c, r, 'ebay.execution.started', actor, 'system')
        try:
            if self.mode == 'DRY_RUN':
                self._validate_before_send(r, payload)
                result = {'dry_run': True, 'payload_hash': payload_hash(payload)}
            elif r['action_type'] == 'CREATE_LISTING':
                self._validate_before_send(r, payload)
                # Simulation must never register a real listing or modify the approved draft.
                result = self.provider.create_listing(payload, idempotency_key=r['idempotency_key'])
            else:
                self._validate_before_send(r, payload)
                method = {'UPDATE_PRICE': 'update_price', 'UPDATE_QUANTITY': 'update_quantity',
                          'END_LISTING': 'end_listing', 'REVISE_LISTING': 'revise_listing'}[r['action_type']]
                result = getattr(self.provider, method)(payload, idempotency_key=r['idempotency_key'])
        except Exception as exc:
            return self._fail(r, actor, exc)
        try:
            if self.mode == 'MOCK' and r['action_type'] != 'CREATE_LISTING':
                self._verify_change_result(r, result)
            return self._finish(r, result, actor)
        except Exception:
            return self._fail(r, actor, PublicationError('UNKNOWN_RESULT', '結果保存の照合が必要です。', uncertain=True))

    def _fail(self, r, actor, exc):
        known = isinstance(exc, PublicationError)
        uncertain = exc.uncertain if known else True
        code = exc.code if known and exc.code in ('DISABLED','INVALID','CONFLICT','STALE','APPROVAL_MISMATCH','FAILED',
            'UNKNOWN_RESULT','TEST_FAILURE','READ_FAILED','AUTH_EXPIRED','RATE_LIMIT') else 'UNKNOWN_RESULT'
        message = '処理結果が未確定です。再送せず結果を照合してください。' if uncertain else 'Mock処理に失敗しました。内容・状態を確認して再試行または再提案してください。'
        if code == 'APPROVAL_MISMATCH' and not uncertain:
            message = '承認済みpayloadと現在の下書きが一致しません。送信はしていません。提案を取り消し、下書きを再承認して再提案してください。'
        elif code == 'STALE' and not uncertain:
            message = '対象の識別子・通貨・現在値が承認版と一致しません。送信していません。取り消して再提案してください。'
        elif code == 'READ_FAILED' and not uncertain:
            message = '実行前の現在値取得に失敗しました。送信していません。接続状態を確認してください。'
        elif code in ('AUTH_EXPIRED', 'RATE_LIMIT') and not uncertain:
            message = '認証期限またはAPI制限によって拒否されました。自動再送はしません。原因を解消してから再確認してください。'
        with self.factory() as c:
            c.execute('BEGIN IMMEDIATE')
            repo = ApprovalRepository(c)
            current = repo.get(r['approval_request_id'])
            if current['status'] != 'EXECUTING' or current['attempt_count'] != r['attempt_count']:
                return current
            repo.update(r['approval_request_id'], status='FAILED', execution_status='UNKNOWN' if uncertain else 'FAILED', error_code=code,
                error_message=message, reconcile_required=int(uncertain), version=current['version'] + 1, updated_at=utc_now())
            c.execute('''UPDATE approval_execution_attempts SET status='FAILED',finished_at=?,error_code=?,error_message=?
                WHERE approval_request_id=? AND attempt_number=?''', (utc_now(), code, message, r['approval_request_id'], r['attempt_count']))
            c.execute("UPDATE outbox_events SET status=?,updated_at=? WHERE event_id=?",
                      ('needs_reconciliation' if uncertain else 'pending', utc_now(), r['outbox_event_id']))
            result = repo.get(r['approval_request_id'])
            self._audit(c, result, 'ebay.execution.failed', actor, 'system', before=current)
            return result

    def reconcile(self, request_id, *, actor_id):
        self._local()
        actor = self._actor(actor_id)
        r = self.get(request_id)
        if not r or r['mode'] != self.mode or not r['reconcile_required'] or r['status'] not in ('FAILED','EXECUTING'):
            raise ValueError('結果照合の対象ではありません。')
        try:
            result = self.provider.lookup_execution(r['idempotency_key'])
        except Exception:
            raise PublicationError('UNKNOWN_RESULT', '実行記録を取得できません。再送せず、後で照合してください。', uncertain=True) from None
        if result is None:
            raise ValueError('実行結果を確認できません。自動再送は行いません。')
        if r['action_type'] != 'CREATE_LISTING':
            self._verify_change_result(r, result)
        return self._finish(r, result, actor, reconciled=True)

    def _verify_change_result(self, r, result):
        validate_result(r['action_type'], json.loads(r['approved_payload_json']), result)
        try:
            remote = self.provider.get_listing(result['external_listing_id'])
        except Exception:
            raise PublicationError('UNKNOWN_RESULT', '出品先の現在値を取得できません。再送せず、後で照合してください。', uncertain=True) from None
        if remote != result:
            raise PublicationError('UNKNOWN_RESULT', '実行記録と出品先の現在値が一致しません。再送せず人間が確認してください。', uncertain=True)

    def _finish(self, r, result, actor, *, reconciled=False):
        with self.factory() as c:
            c.execute('BEGIN IMMEDIATE')
            repo = ApprovalRepository(c)
            current = repo.get(r['approval_request_id'])
            if current['status'] == 'SUCCEEDED':
                return current
            if current['attempt_count'] != r['attempt_count'] or current['status'] not in ('EXECUTING','FAILED'):
                raise ValueError('実行状態が変更されています。')
            external = None
            marketplace_id = current['marketplace_listing_id']
            if current['mode'] == 'MOCK':
                external = result['external_listing_id']
                if not external.startswith('MOCK-'):
                    raise ValueError('Mock以外の出品IDは保存できません。')
                if r['action_type'] == 'CREATE_LISTING':
                    frozen = json.loads(current['approved_payload_json'])
                    if result['payload'] != frozen or result['version'] != 1 or result['status'] != 'ACTIVE':
                        raise ValueError('承認済みpayloadとMock実行結果が一致しません。')
                    marketplace_id = current['publication_id']
                    c.execute('''INSERT INTO marketplace_listings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (marketplace_id, current['product_id'], current['listing_draft_id'], current['publication_id'], None,
                         r['approval_request_id'], external, frozen['sku'], frozen['site'], 'MOCK', result['status'],
                         encode(result['payload']), result['version'], utc_now(), utc_now()))
                else:
                    listing = marketplace_record(c, marketplace_id)
                    payload = json.loads(current['approved_payload_json'])
                    self._current(c, current, payload)
                    validate_result(current['action_type'], payload, result)
                    # Preserve historical profits/shipping JSON in the legacy listing.
                    c.execute('''UPDATE marketplace_listings SET current_payload_json=?,status=?,version=?,updated_at=?,
                        approval_request_id=? WHERE marketplace_listing_id=?''',
                        (encode(result['payload']), result['status'], result['version'], utc_now(), r['approval_request_id'], marketplace_id))
            execution_status = 'DRY_RUN' if r['mode']=='DRY_RUN' else 'RECONCILED' if reconciled else 'SUCCEEDED'
            repo.update(r['approval_request_id'], status='SUCCEEDED', execution_status=execution_status,
                result_json=encode(result), external_listing_id=external, marketplace_listing_id=marketplace_id,
                executed_at=utc_now(), updated_at=utc_now(), reconcile_required=0, error_message=None, error_code=None,
                version=current['version'] + 1)
            OutboxRepository(c).mark_processed(r['outbox_event_id'])
            c.execute('''UPDATE approval_execution_attempts SET status='SUCCEEDED',finished_at=?,result_json=?
                WHERE approval_request_id=? AND attempt_number=?''', (utc_now(), encode(result), r['approval_request_id'], r['attempt_count']))
            after = repo.get(r['approval_request_id'])
            self._audit(c, after, 'ebay.execution.succeeded', actor, 'system', before=current)
            if reconciled:
                self._audit(c, after, 'ebay.execution.reconciled', actor, 'human')
            if r['mode'] == 'MOCK':
                action = 'listing.mock_published' if r['action_type']=='CREATE_LISTING' else 'listing.mock_ended' if r['action_type']=='END_LISTING' else 'listing.mock_updated'
                self._audit(c, after, action, actor, 'system')
            return after

    def execute_next(self, *, actor_id):
        self._local()
        with self.factory() as c:
            row = c.execute('''SELECT a.approval_request_id FROM approval_requests a JOIN outbox_events o
                ON o.event_id=a.outbox_event_id WHERE o.event_type=? AND o.status='pending'
                AND a.status='APPROVED' AND a.mode=? ORDER BY a.approved_at LIMIT 1''', (EVENT_TYPE, self.mode)).fetchone()
        return self.execute(row[0], actor_id=actor_id) if row else None
