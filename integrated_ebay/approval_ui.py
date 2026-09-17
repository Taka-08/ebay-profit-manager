"""Human review and explicit local-only execution, never a background worker."""

import json

import streamlit as st

from .approval_migration import approval_schema_ready
from .approval_service import ACTIONS, STATUSES, ApprovalService
from .ebay_api import execution_mode
from .publication_provider import PublicationError
from .publication_service import PublicationService


def _run(operation, message):
    try:
        result = operation()
    except (ValueError, PublicationError) as exc:
        st.error(str(exc))
        return
    except Exception:
        st.error('処理状態を確認できません。再実行せず履歴を確認してください。')
        return
    if result and result.get('status') == 'FAILED':
        st.session_state['approval_notice'] = result['error_message']
    else:
        st.session_state['approval_notice'] = message
    st.rerun()


def _open_approval(request_id):
    st.session_state['manager_main_tab'] = '承認・実行'
    st.session_state['approval_selected'] = request_id


def render_draft_approval_link(factory, draft, actor):
    if not approval_schema_ready(factory):
        return False
    service = ApprovalService(factory)
    active = next((r for r in service.list() if r['listing_draft_id'] == draft['listing_draft_id']
                   and r['mode'] == service.mode and r['action_type'] == 'CREATE_LISTING'
                   and r['status'] not in ('REJECTED', 'CANCELLED')), None)
    if active:
        st.info(f"承認・実行キュー: {active['status']} / {active['mode']}")
        st.button('承認・実行で確認', key='draft_queue_open', use_container_width=True,
                  on_click=_open_approval, args=(active['approval_request_id'],))
        return True
    pub = PublicationService(factory).get(draft['listing_draft_id'])
    if pub and pub['status'] == 'APPROVED':
        prior = next((r['approval_request_id'] for r in service.list() if r['publication_id'] == pub['publication_id']
                      and r['mode'] == service.mode), 'initial')
        disabled = service.mode not in ('MOCK', 'DRY_RUN')
        if st.button('公開提案を承認キューへ', key='draft_queue_create', disabled=disabled,
                     type='primary', use_container_width=True):
            _run(lambda: service.propose_create(draft['listing_draft_id'], actor_id=actor,
                idempotency_key=f"create:{service.mode}:{pub['publication_id']}:{prior}"), '公開提案を作成しました。まだ実行されません。')
        return True
    return False


def _changes(action, values, prefix):
    changes = {}
    if action in ('UPDATE_PRICE', 'REVISE_LISTING'):
        changes['price'] = st.number_input('提案価格', min_value=0.01,
            value=max(0.01, float(values.get('price', 1))), step=0.01, key=prefix+'_price')
    if action in ('UPDATE_QUANTITY', 'REVISE_LISTING'):
        changes['quantity'] = st.number_input('提案数量', min_value=0,
            value=int(values.get('quantity', 0)), step=1, key=prefix+'_quantity')
    if action == 'REVISE_LISTING':
        changes['title'] = st.text_input('Title', value=values.get('title', ''), max_chars=80, key=prefix+'_title')
        changes['description'] = st.text_area('Description', value=values.get('description', ''), key=prefix+'_description')
    return changes


def _comparison(row):
    before = json.loads(row['before_payload_json'])
    proposed = json.loads(row['proposed_payload_json'])
    changes = proposed if row['action_type'] == 'CREATE_LISTING' else proposed['changes']
    currency = before.get('currency', proposed.get('currency', ''))
    st.write(f"{row['action_type']} · {row['status']} · {row['mode']}")
    st.caption(f"実行状態: {row['execution_status']} / 承認者: {row['approved_by'] or '未承認'} / 実行日時: {row['executed_at'] or '未実行'}")
    st.caption(f"{row['created_at']} / {row['created_actor_type']}:{row['created_by']}")
    if 'price' in changes:
        old, new = before.get('price'), changes['price']
        st.write(f"価格 ({currency}): {old if old is not None else '新規'} → {new:,.2f}")
        if old is not None:
            delta = new - old
            rate = f'{delta / old * 100:+.2f}%' if old else '計算対象外'
            st.caption(f'差額: {delta:+,.2f} / 変更率: {rate}')
    if 'quantity' in changes:
        st.write(f"数量: {before.get('quantity', '新規')} → {changes['quantity']}")
        if changes['quantity'] == 0:
            st.caption('数量0として保持します。出品終了とは別の操作です。')
    if row['action_type'] == 'END_LISTING':
        st.warning('状態: ACTIVE → ENDED（出品終了）')
    target = proposed.get('target', {})
    if target:
        st.text(f"SKU: {target['sku']} / Marketplace: {target['marketplace']} / 通貨: {target['currency']}")
        st.text('商品ID: ' + target['product_id'])
        if row['mode'] == 'SANDBOX':
            st.text('Sandbox Offer ID: ' + target['offer_id'])
            st.text('Seller照合ID: ' + target['seller_account'])
    if proposed.get('external_listing_id'):
        st.text('Item ID: ' + proposed['external_listing_id'])
    st.text('理由: ' + row['reason'])
    if row['source_status']:
        st.text('仕入先状況（申告値）: ' + row['source_status'])


def _propose_update(service, actor, disabled):
    targets = {r['marketplace_listing_id']: r for r in service.listings() if r['status'] == 'ACTIVE'}
    sandbox = service.mode == 'SANDBOX'
    with st.expander('Sandbox出品の変更を提案' if sandbox else 'Mock出品の変更を提案'):
        if not targets:
            st.caption('検証用Offerを読み取り確認してSandbox専用DBへ紐付ける必要があります。通常の出品管理データは変更しません。' if sandbox else '第6段階のMock実行結果を保存した後に選択できます。通常の出品管理データは変更しません。')
            return
        target = st.selectbox('対象Sandbox出品' if sandbox else '対象Mock出品', list(targets),
            format_func=lambda k: targets[k]['product_name'] + ' / ' + targets[k]['external_listing_id'], key='proposal_target')
        action = st.selectbox('操作', ACTIONS[1:4] if sandbox else ACTIONS[1:], key='proposal_action')
        listing = targets[target]
        if sandbox:
            refresh_ok = st.checkbox('未実行の提案を取消済みです。Sandbox現在値を再取得します', key='sandbox_refresh_confirm')
            if st.button('再提案用の現在値を取得', disabled=disabled or not refresh_ok, use_container_width=True):
                _run(lambda: service.refresh_test_offer(target, actor_id=actor, refresh_confirmed=refresh_ok),
                     '現在値を取得しました。変更を反映するには新しい提案と承認が必要です。')
        values = json.loads(listing['current_payload_json'])
        prior = next((r['approval_request_id'] for r in service.list() if r['marketplace_listing_id'] == target
                      and r['action_type'] == action and r['mode'] == service.mode), 'initial')
        prefix = f"proposal_{target}_{listing['version']}_{action}_{prior}_{service.mode}"
        with st.form(prefix):
            st.caption(f"現在価格: {values['price']:,.2f} {values['currency']} / 現在数量: {values['quantity']}")
            changes = _changes(action, values, prefix)
            reason = st.text_input('変更理由', key=prefix+'_reason')
            source = st.text_input('仕入先状況（任意・自動監視なし）', key=prefix+'_source')
            submitted = st.form_submit_button('変更提案を保存', disabled=disabled, use_container_width=True)
        if submitted:
            _run(lambda: service.propose_change(target, action, changes, reason=reason, source_status=source,
                actor_id=actor, idempotency_key=prefix), '変更提案を保存しました。承認前には実行されません。')


def _review(service, row, actor, disabled):
    rid, version = row['approval_request_id'], row['version']
    prefix = f'approval_{rid}_{version}'
    payload = json.loads(row['proposed_payload_json'])
    if row['status'] == 'PENDING':
        if row['action_type'] == 'CREATE_LISTING':
            st.caption('本文の修正は、この提案を取り消した後、AI出品の下書きで保存・再承認してください。')
            changes, reason = None, row['reason']
        else:
            with st.expander('提案内容を編集'):
                values = {**json.loads(row['before_payload_json']), **payload['changes']}
                changes = _changes(row['action_type'], values, prefix)
                reason = st.text_input('変更理由', value=row['reason'], key=prefix+'_reason')
        reviewed = st.checkbox('提案内容を人間が確認しました', key=prefix+'_reviewed')
        st.caption('「提案を承認」は保存済み内容が対象です。入力変更を反映する場合は「編集して承認」を使用してください。')
        end = row['action_type'] == 'END_LISTING'
        confirmed = st.checkbox('このSandbox出品を終了することを最終確認しました' if row['mode'] == 'SANDBOX' else 'このMock出品を終了することを最終確認しました', key=prefix+'_end') if end else False
        cols = st.columns(3)
        if cols[0].button('提案を承認', key=prefix+'_approve', type='primary', disabled=disabled or not reviewed or (end and not confirmed), use_container_width=True):
            _run(lambda: service.approve(rid, expected_version=version, actor_id=actor,
                reviewed=reviewed, end_confirmed=confirmed), '承認済みpayloadを固定し、Outboxへ登録しました。')
        if cols[1].button('提案を却下', key=prefix+'_reject', disabled=disabled, use_container_width=True):
            _run(lambda: service.reject(rid, expected_version=version, actor_id=actor), '却下しました。')
        if cols[2].button('編集して承認', key=prefix+'_edit_approve', disabled=disabled or changes is None or not reviewed or (end and not confirmed), use_container_width=True):
            def edit_approve():
                saved = service.edit(rid, changes, reason=reason, expected_version=version, actor_id=actor)
                return service.approve(rid, expected_version=saved['version'], actor_id=actor,
                    reviewed=reviewed, end_confirmed=confirmed)
            _run(edit_approve, '編集内容を保存・承認し、Outboxへ登録しました。')
    if row['status'] in ('APPROVED', 'FAILED', 'EXECUTING'):
        if row['error_message']:
            st.error(row['error_code'] + ': ' + row['error_message'])
        st.caption(f"試行回数: {row['attempt_count']} / 最終試行: {row['last_attempt_at'] or '未実行'}")
        if row['reconcile_required']:
            if st.button('実行結果を照合（再送なし）', key=prefix+'_reconcile', disabled=disabled, use_container_width=True):
                _run(lambda: service.reconcile(rid, actor_id=actor), '保存済みの実行結果を照合しました。')
        else:
            confirm_label = '出品終了のMock実行を確認しました' if row['action_type'] == 'END_LISTING' else '第6段階専用データへのMock/Dry-run保存を確認しました'
            if row['mode'] == 'SANDBOX':
                confirm_label = 'Sandboxのテスト出品に実際の変更を送信することを確認しました'
            execute_ok = st.checkbox(confirm_label, key=prefix+'_execute_confirm')
            label = 'Sandbox実行' if row['mode'] == 'SANDBOX' else 'Mock実行' if row['mode'] == 'MOCK' else 'Dry-run実行'
            if row['status'] == 'FAILED':
                label += 'を再試行'
            if st.button(label, key=prefix+'_execute', disabled=disabled or not execute_ok, type='primary', use_container_width=True):
                _run(lambda: service.execute(rid, actor_id=actor), 'Sandbox結果を保存しました。Productionは変更していません。' if row['mode'] == 'SANDBOX' else '実行結果を保存しました。実eBayへの変更はありません。')
    if row['status'] in ('PENDING', 'APPROVED', 'FAILED') and not row['reconcile_required']:
        if st.button('提案を取り消す', key=prefix+'_cancel', disabled=disabled, use_container_width=True):
            _run(lambda: service.cancel(rid, expected_version=version, actor_id=actor), '提案を取り消しました。')
    if row['status'] == 'SUCCEEDED':
        st.success('Sandbox実行・現在値照合済み' if row['mode'] == 'SANDBOX' else 'Dry-run検証済み（未送信）' if row['mode'] == 'DRY_RUN' else 'Mock実行済み')
        if row['execution_status'] == 'RECONCILED':
            st.caption('RECONCILED: 保存済みの実行記録と現在値を照合済み（再送なし）')
        st.text('外部出品ID: ' + str(row['external_listing_id'] or 'なし'))
    with st.expander('固定payload・実行履歴'):
        st.json(json.loads(row['approved_payload_json'] or row['proposed_payload_json']), expanded=False)
        for attempt in service.history(rid):
            st.write(f"{attempt['attempt_number']} / {attempt['status']} / {attempt['started_at']} / {attempt['actor_id']}")
            if attempt['error_code']:
                st.text(attempt['error_code'] + ': ' + attempt['error_message'])
        if row['result_json']:
            st.json(json.loads(row['result_json']), expanded=False)


def render_approvals(factory, calculate_expected=None):
    with st.container(key='approval_workspace'):
        st.markdown('''<style>
        .st-key-approval_workspace {min-width:0;overflow-wrap:anywhere;}
        .st-key-approval_workspace [data-testid="stText"] {white-space:pre-wrap;overflow-wrap:anywhere;}
        .st-key-approval_workspace [data-testid="stButton"] button,
        .st-key-approval_workspace [data-testid="stFormSubmitButton"] button {min-height:46px;}
        @media(max-width:768px) {
          .st-key-approval_workspace [data-testid="stHorizontalBlock"] {flex-direction:column;}
          .st-key-approval_workspace [data-testid="stColumn"] {width:100%!important;flex:1 1 100%!important;min-width:0;}
          .st-key-approval_workspace [data-testid="stButton"] button,
          .st-key-approval_workspace [data-testid="stFormSubmitButton"] button {width:100%;min-height:46px;white-space:normal;}
          .st-key-approval_workspace textarea {max-width:100%;}
        }</style>''', unsafe_allow_html=True)
        st.header('承認・実行')
        try:
            mode = execution_mode()
        except ValueError as exc:
            st.error(str(exc))
            return
        st.info(f'現在のeBay実行モード: {mode} / Production書き込み無効')
        if mode != 'SANDBOX':
            st.caption('外部eBay通信は無効です。実eBayへの変更は発生しません。')
        if not approval_schema_ready(factory):
            st.warning('第6段階のDB基盤は未適用です。本番への適用にはバックアップと別途承認が必要です。')
            return
        disabled = mode not in ('MOCK', 'DRY_RUN', 'SANDBOX')
        if disabled:
            st.warning('Sandbox・Productionは実行できません。Mock/Dry-runに限定しています。')
        if mode == 'SANDBOX':
            from .sandbox_migration import sandbox_schema_ready
            from .sandbox_service import SandboxApprovalService
            if not sandbox_schema_ready(factory):
                st.warning('Sandbox専用DBは未適用です。本番DBには自動適用しません。')
                return
            service = SandboxApprovalService(factory)
            try:
                service._local()
            except PublicationError as exc:
                st.warning(str(exc))
                return
            st.warning('Sandbox専用テスト出品への実通信です。新規公開・Production・通常出品管理登録は無効です。')
        else:
            st.caption('Mock結果・承認履歴は接続中DBの第6段階用データに保存します。通常の出品・送料・利益データは変更しません。')
            service = ApprovalService(factory, calculate_expected=calculate_expected, mode=mode)
        notice = st.session_state.pop('approval_notice', None)
        if notice:
            st.info(notice)
        actor = st.text_input('確認・実行する人の名前', key='approval_actor')
        _propose_update(service, actor, disabled)
        rows = service.list()
        labels = {'PENDING':'承認待ち', 'APPROVED':'承認済み', 'SUCCEEDED':'実行済み', 'FAILED':'失敗'}
        selected_status = st.selectbox('状態で絞り込み', ('ALL', *STATUSES),
            format_func=lambda s: 'すべて' if s == 'ALL' else labels.get(s, s), key='approval_filter')
        rows = [r for r in rows if selected_status == 'ALL' or r['status'] == selected_status]
        if not rows:
            st.info('該当する提案はありません。')
            return
        by_id = {r['approval_request_id']: r for r in rows}
        if st.session_state.get('approval_selected') not in by_id:
            st.session_state['approval_selected'] = rows[0]['approval_request_id']
        selected = st.selectbox('確認する提案', list(by_id), key='approval_selected',
            format_func=lambda k: f"{by_id[k]['product_name']} / {by_id[k]['action_type']} / {k[-8:]}")
        st.caption('選択中の状態: ' + by_id[selected]['status'])
        for row in rows:
            with st.expander(f"{row['product_name']} / {row['action_type']} / {row['status']}", expanded=row['approval_request_id']==selected):
                _comparison(row)
        st.subheader(by_id[selected]['product_name'])
        _review(service, by_id[selected], actor, disabled or by_id[selected]['mode'] != mode)
