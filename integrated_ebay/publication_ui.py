"""Approval inputs and explicit no-network publication controls."""

import json
import logging
import streamlit as st
from app_database import remote_database_is_configured
from .publication_service import PublicationService
from .publication_validation import publication_inputs


def edit_publication_inputs(draft, *, disabled):
    p = publication_inputs(draft)
    with st.expander('公開前の商品・配送・費用確認', expanded=False):
        st.caption('この版の確認値として保存します。商品マスター・保存済み送料は書き換えません。')
        row = st.columns(2)
        for index, (key, label) in enumerate((('sku', 'SKU'), ('country_of_origin', '原産国（ISO2）'),
                                             ('hs_code', 'HS Code'), ('hts_code', 'HTS Code'))):
            p[key] = row[index % 2].text_input(label, value=str(p.get(key) or ''), disabled=disabled)
        p['source_url'] = st.text_input('仕入元URL', value=p.get('source_url') or '', disabled=disabled)
        row = st.columns(4)
        for index, (key, label) in enumerate((('weight_g', '実重量（g）'), ('length_cm', '長さ（cm）'),
                                             ('width_cm', '幅（cm）'), ('height_cm', '高さ（cm）'))):
            p[key] = row[index].number_input(label, min_value=0.0, value=float(p[key] or 0), disabled=disabled)
        row = st.columns(2)
        p['purchase_price'] = row[0].number_input('仕入価格（円）', min_value=0.0, value=float(p['purchase_price'] or 0), disabled=disabled)
        p['purchase_currency'] = row[1].text_input('仕入通貨（円換算済みはJPY）', value=p['purchase_currency'] or 'JPY', disabled=disabled)
        row = st.columns(3)
        p['shipping_carrier'] = row[0].text_input('予定配送会社', value=p['shipping_carrier'] or '', disabled=disabled)
        p['shipping_service'] = row[1].text_input('予定配送サービス', value=p['shipping_service'] or '', disabled=disabled)
        p['shipping_yen'] = row[2].number_input('予定送料合計（円）', min_value=0.0, value=float(p['shipping_yen']) if p['shipping_yen'] is not None else None, disabled=disabled)
        row = st.columns(2)
        fields = (('exchange_rate', '商品通貨/JPYレート'), ('usd_jpy_rate', '固定手数料用USD/JPYレート'),
                  ('buyer_shipping_usd', '購入者負担送料（商品通貨）'), ('ebay_fee_rate', '予定eBay手数料率（%）'),
                  ('promoted_listing_rate', '予定広告率（%）'), ('exchange_spread_rate', '予定海外手数料率（%）'),
                  ('fixed_fee_usd', '予定固定手数料（USD）'), ('domestic_shipping_yen', '国内送料（円）'),
                  ('packaging_yen', '梱包費（円）'), ('other_cost_yen', 'その他費用（円）'))
        for index, (key, label) in enumerate(fields):
            p[key] = row[index % 2].number_input(label, min_value=0.0,
                value=float(p[key]) if p.get(key) is not None else None, disabled=disabled)
        required = st.text_area('必須Item Specifics名（1行1項目）', value='\n'.join(p.get('required_specifics') or []), disabled=disabled)
        p['required_specifics'] = [line.strip() for line in required.splitlines() if line.strip()]
        p['specifics_reviewed'] = st.checkbox('Categoryごとの必須Item Specificsを確認済み（eBay API未照合）',
                                            value=p.get('specifics_reviewed') is True, disabled=disabled)
        st.caption('必須項目の公式自動取得は未接続です。Mock検証用の確認であり、本番出品の適合保証ではありません。')
    p.pop('shipping_breakdown_json', None)
    return json.dumps(p, ensure_ascii=False, allow_nan=False)


def render_publication(service, draft, calculate_expected):
    record = PublicationService(service.connection_factory).get(draft['listing_draft_id'])
    if not record:
        return
    with st.container(border=True):
        st.subheader('公開処理（Mock検証）')
        st.caption(f"{record['status']} / 試行 {record['attempt_count']}回 / 再試行 {max(0, record['attempt_count'] - 1)}回")
        st.warning('実eBayへの出品は無効です。Mock公開はローカル検証DBのみで実行でき、出品管理に検証用データを作成します。')
        if record['error_message']:
            st.error(f"{record['error_code']}: {record['error_message']} ({record['failed_at']})")
        if record['status'] == 'PUBLISHED':
            st.text(f"Mock Item ID: {record['ebay_item_id']}\n出品管理ID: {record['listing_id']}\n公開日時: {record['published_at']}")
            return
        enabled = st.checkbox('ローカル検証DBへのMock登録を確認して実行する',
                              key=record['publication_id'] + '_mock', disabled=remote_database_is_configured())
        actor = st.session_state.get('ai_draft_actor', '')
        publisher = PublicationService(service.connection_factory, calculate_expected=calculate_expected, allow_mock=enabled)
        uncertain = record['status'] == 'PUBLISHING' or bool(record['reconcile_required'])
        label = '公開結果を照合（再送しない）' if uncertain else 'Mockで公開' if record['status'] == 'APPROVED' else 'Mock公開を再試行'
        if st.button(label, key=record['publication_id'] + '_publish', disabled=not enabled, use_container_width=True):
            try:
                with st.spinner('公開結果を確認しています...'):
                    result = (publisher.reconcile if uncertain else publisher.publish)(draft['listing_draft_id'], actor_id=actor)
                st.session_state['ai_draft_notice'] = 'Mock公開・出品管理への紐付けが完了しました。' if result['status'] == 'PUBLISHED' else '公開は失敗しました。下書きは保持されています。'
                st.rerun()
            except Exception as exc:
                logging.getLogger(__name__).exception('Publication failed for draft %s', draft['listing_draft_id'])
                st.error(str(exc) if isinstance(exc, ValueError) else '保存を完了できませんでした。再送せず公開結果を照合してください。')
