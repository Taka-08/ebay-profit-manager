"""Human review and explicitly isolated Mock publication UI."""

import html
import json
from urllib.parse import urlsplit

import streamlit as st

from .draft_service import DRAFT_CURRENCIES, DRAFT_SITES, DRAFT_STATUSES, ListingDraftService
from .publication_ui import edit_publication_inputs, render_publication
from .publication_service import PublicationService, effective_status


def open_product_drafts(product_id):
    st.session_state["ai_product_id"] = product_id
    st.session_state["manager_main_tab"] = "AI出品"
    st.session_state.pop("ai_selected_draft", None)


def _notice(message):
    st.session_state["ai_draft_notice"] = message
    st.rerun()


def _context(service, product_id):
    context = service.context(product_id)
    with st.expander("商品・在庫・仕入先・画像", expanded=False):
        st.json(context["product"], expanded=False)
        stock = context["available_quantity"]
        st.write(f"利用可能在庫: {stock if stock is not None else '未確定（要確認）'}")
        for source in context["sources"]:
            st.text(f"{source.get('source_name', '')}\n{source.get('source_url', '')}")
        for image in context["images"]:
            st.text(f"画像: {image.get('file_name') or image.get('image_id')}\n{image.get('url') or image.get('storage_key')}")
        if context["images"] and st.checkbox("画像プレビューを表示", key=f"ai_images_{product_id}"):
            for image in context["images"]:
                url = str(image.get("url") or "")
                try:
                    parsed = urlsplit(url)
                    can_preview = parsed.scheme == "https" and parsed.hostname and not parsed.username
                except ValueError:
                    can_preview = False
                if can_preview:
                    # Browser-only image: no server-side download of arbitrary URLs.
                    st.markdown('<img class="draft-image" referrerpolicy="no-referrer" src="' + html.escape(url, quote=True) + '" alt="商品画像">', unsafe_allow_html=True)
                else:
                    st.caption("プレビューできるHTTPS URLがありません。画像メタデータのみ保持します。")
        st.caption("画像内容の解析・仕入先URLへの自動アクセスは行いません。")


def _editor(service, draft, actor, calculate_expected=None):
    draft_id, revision = draft["listing_draft_id"], draft["revision"]
    prefix = f"draft_{draft_id}_{revision}"
    st.subheader("下書きを編集")
    publication = PublicationService(service.connection_factory).get(draft_id)
    st.caption(f"{draft_id} / revision {revision} / {effective_status(draft, publication)}")
    notes = json.loads(draft["review_notes_json"])
    for note in notes:
        st.warning(str(note))
    with st.expander("生成元・根拠・要確認項目", expanded=False):
        st.json(json.loads(draft["generation_output_json"]), expanded=False)
        st.caption(f"モデル: {draft['ai_model'] or '未生成'} / Prompt: {draft['prompt_version'] or 'なし'}")
    archived = draft["status"] == "ARCHIVED" or bool(publication and publication['status'] in ('PUBLISHING', 'PUBLISHED', 'FAILED'))
    with st.form(prefix, clear_on_submit=False):
        title = st.text_input("Title", value=draft["title"], max_chars=service.generator.policy.title_limit, disabled=archived)
        description = st.text_area("Description", value=draft["description"], height=280, disabled=archived)
        cat = st.columns(2)
        category_name = cat[0].text_input("Category（ローカル候補・要確認）", value=draft["category_name"] or "", disabled=archived)
        category_id = cat[1].text_input("Category ID（承認時必須・未照合）", value=draft["category_id"] or "", disabled=archived)
        cond = st.columns(2)
        condition_name = cond[0].text_input("Condition（例: New / Used、要現物確認）", value=draft["condition_name"] or "", disabled=archived)
        condition_id = cond[1].text_input("Condition ID（承認時必須・未照合）", value=draft["condition_id"] or "", disabled=archived)
        st.caption("傷・使用感・動作確認・欠品はDescriptionへ記録してください。")
        row = st.columns(4)
        price = row[0].number_input("Price", min_value=0.0, value=draft["price"], step=0.01, disabled=archived)
        currency = row[1].selectbox("Currency", DRAFT_CURRENCIES, index=DRAFT_CURRENCIES.index(draft["currency"]), disabled=archived)
        quantity = row[2].number_input("Quantity", min_value=0, value=draft["quantity"], step=1, disabled=archived)
        site = row[3].selectbox("eBay site", DRAFT_SITES, index=DRAFT_SITES.index(draft["site"]), disabled=archived)
        specifics = st.text_area("Item Specifics（JSON）", value=json.dumps(json.loads(draft["item_specifics_json"]), ensure_ascii=False, indent=2), height=260, disabled=archived)
        profile = st.text_area("Shipping profile（保存済みスナップショット・JSON）", value=draft["shipping_profile_json"], disabled=archived)
        review_notes = st.text_area("確認メモ（1行1件）", value="\n".join(str(x) for x in notes), disabled=archived)
        publication_input = edit_publication_inputs(draft, disabled=archived)
        saved = st.form_submit_button("下書きを保存", type="primary", disabled=archived, use_container_width=True)
    if saved:
        try:
            service.update(draft_id, {
                "title": title, "description": description, "category_name": category_name.strip() or None,
                "category_id": category_id.strip() or None, "condition_name": condition_name.strip() or None,
                "condition_id": condition_id.strip() or None, "price": price, "currency": currency,
                "quantity": quantity, "site": site, "item_specifics_json": specifics,
                "shipping_profile_json": profile, "review_notes_json": json.dumps(review_notes.splitlines(), ensure_ascii=False),
                "publication_input_json": publication_input,
            }, expected_revision=revision, actor_id=actor)
            _notice("保存しました。編集後は承認が解除され、DRAFTに戻ります。")
        except ValueError as exc:
            st.error(str(exc))
    if not archived:
        confirmed = st.checkbox("保存済み本文を再生成する（現在の内容は履歴に残す）", key=prefix + "_regen_confirm")
        if st.button("AIで再生成", key=prefix + "_regen", disabled=not confirmed, use_container_width=True):
            try:
                with st.spinner("下書きを生成しています..."):
                    service.generate(draft_id, expected_revision=revision, actor_id=actor)
                _notice("再生成しました。価格・数量・送料スナップショットは変更していません。")
            except ValueError as exc:
                st.error(str(exc))
        if st.button("レビュー待ちにする", key=prefix + "_ready", use_container_width=True):
            _transition(service, draft, "READY_FOR_REVIEW", actor)
        reviewed = st.checkbox("保存済みの本文・状態・価格・数量・未確認事項を人間が確認しました", key=prefix + "_reviewed")
        st.caption("以下の操作は保存済みの版に対して行います。フォームの変更は先に保存してください。承認してもeBayへ出品されません。")
        actions = st.columns(3)
        if actions[0].button("承認", key=prefix + "_approve", type="primary", disabled=not reviewed or draft["status"] != "READY_FOR_REVIEW", use_container_width=True):
            _transition(service, draft, "APPROVED", actor, reviewed=True)
        if actions[1].button("却下", key=prefix + "_reject", use_container_width=True):
            _transition(service, draft, "REJECTED", actor)
        if actions[2].button("アーカイブ", key=prefix + "_archive", use_container_width=True):
            _transition(service, draft, "ARCHIVED", actor)
    render_publication(service, draft, calculate_expected)
    with st.expander("変更履歴", expanded=False):
        for item in service.revisions(draft_id):
            with st.expander(f"r{item['revision']} {item['action']} / {item['actor_type']}:{item['actor_id']} / {item['created_at']}"):
                st.json(json.loads(item["snapshot_json"]), expanded=False)


def _transition(service, draft, status, actor, reviewed=False):
    try:
        service.transition(draft["listing_draft_id"], status, expected_revision=draft["revision"], actor_id=actor, reviewed=reviewed)
        _notice(f"{status}に変更しました。外部サービスへの送信はありません。")
    except ValueError as exc:
        st.error(str(exc))


def render_listing_drafts(connection_factory, calculate_expected=None):
    service = ListingDraftService(connection_factory)
    with st.container(key="ai_listing_workspace"):
        st.markdown("""<style>
        .draft-image {max-width:100%; max-height:300px; object-fit:contain;}
        .draft-mobile-list {display:none;}
        .draft-card {border:1px solid color-mix(in srgb,currentColor 25%,transparent);border-radius:8px;padding:12px;margin:8px 0;overflow-wrap:anywhere;}
        @media(max-width:768px) {
          .st-key-ai_listing_workspace [data-testid="stHorizontalBlock"] {flex-direction:column;}
          .st-key-ai_listing_workspace [data-testid="stColumn"] {width:100%!important;flex:1 1 100%!important;min-width:0;}
          .st-key-ai_listing_workspace [data-testid="stButton"] button,
          .st-key-ai_listing_workspace [data-testid="stFormSubmitButton"] button {width:100%;min-height:46px;white-space:normal;}
          .st-key-ai_listing_workspace [data-testid="stSelectbox"] button,
          .st-key-ai_listing_workspace [data-testid="stNumberInput"] button {width:auto!important;min-width:0!important;flex:0 0 auto;}
          .st-key-ai_listing_workspace textarea {max-width:100%;}
          .st-key-draft_desktop_list {display:none;}
          .draft-mobile-list {display:block;}
        }
        </style>""", unsafe_allow_html=True)
        st.header("AI出品")
        st.info("ローカル生成モード（外部AI未接続）。承認後にMock公開を検証できます。実eBayへの送信は行いません。")
        notice = st.session_state.pop("ai_draft_notice", None)
        if notice:
            st.success(notice)
        actor = st.text_input("操作者名（監査記録用・ログイン認証ではありません）", key="ai_draft_actor")
        products = service.catalog.list_products(status="ALL")
        if not products:
            st.info("商品マスターに商品を登録すると、ここで下書きを作成できます。")
            return
        ids = [p["product_id"] for p in products]
        labels = {p["product_id"]: f"{p['product_name']} / {p.get('sku') or p['product_id']}" for p in products}
        if st.session_state.get("ai_product_id") not in ids:
            st.session_state["ai_product_id"] = ids[0]
        product_id = st.selectbox("下書きの商品", ids, format_func=labels.get, key="ai_product_id")
        _context(service, product_id)
        calculations = service.saved_calculations(product_id)
        with st.expander("新しい下書きを作成", expanded=True):
            selected = st.selectbox("価格・送料の参照元", [None, *[r["id"] for r in calculations]],
                                    format_func=lambda value: "手入力（AIは価格を決定しません）" if value is None else f"保存済み利益計算 / 出品ID {value}", key=f"ai_source_{product_id}")
            source = next((row for row in calculations if row["id"] == selected), {})
            source_currency = source.get("currency_code") or "USD"
            source_price = source.get("listing_price_usd")
            if source_price is None:
                source_price = source.get("listing_price")
            input_key = f"{product_id}_{selected}"
            cols = st.columns(3)
            site = cols[0].selectbox("作成先サイト", DRAFT_SITES, key="ai_new_site")
            currency = cols[1].selectbox("販売通貨", DRAFT_CURRENCIES, index=DRAFT_CURRENCIES.index(source_currency) if source_currency in DRAFT_CURRENCIES else 0, key=f"ai_new_currency_{input_key}", disabled=selected is not None)
            price = cols[2].number_input("販売価格（空欄可）", min_value=0.0, value=float(source_price) if source_price is not None else None, step=0.01, key=f"ai_new_price_{input_key}", disabled=selected is not None)
            if st.button("AI下書きを生成", key="ai_create", type="primary", use_container_width=True):
                try:
                    draft_id = service.create(product_id, actor_id=actor, site=site, currency=currency, price=price, calculation_id=selected)
                    st.session_state["ai_selected_draft"] = draft_id
                    with st.spinner("下書きを生成しています..."):
                        service.generate(draft_id, expected_revision=1, actor_id=actor)
                    _notice("下書きを作成しました。要確認項目を確認してください。")
                except ValueError as exc:
                    st.error(str(exc))
        status = st.selectbox("下書きの状態で絞り込み", ("ALL", *DRAFT_STATUSES, 'PUBLISHING', 'PUBLISHED', 'FAILED'), key="ai_status_filter")
        drafts = service.list(product_id)
        publisher = PublicationService(connection_factory)
        drafts = [dict(d, status=effective_status(d, publisher.get(d['listing_draft_id']))) for d in drafts]
        drafts = [d for d in drafts if status == 'ALL' or d['status'] == status]
        if not drafts:
            st.info("条件に一致する下書きがありません。")
            return
        with st.container(key="draft_desktop_list"):
            st.dataframe([{"商品名": d["product_name"], "Title": d["title"], "状態": d["status"],
                           "作成日時": d["created_at"], "更新日時": d["updated_at"],
                           "最終編集": "AI生成" if d["last_actor_type"] == "ai" else "手動編集",
                           "承認者": d["approved_by"], "版": d["revision"]} for d in drafts], hide_index=True, use_container_width=True)
        cards = []
        for d in drafts:
            content = [d["product_name"], d["title"] or "未生成", d["status"],
                       f"作成 {d['created_at']}", f"更新 {d['updated_at']}",
                       "AI生成" if d["last_actor_type"] == "ai" else "手動編集",
                       f"承認者 {d['approved_by'] or '未承認'}"]
            cards.append('<div class="draft-card">' + '<br>'.join(html.escape(str(x)) for x in content) + '</div>')
        st.markdown('<div class="draft-mobile-list">' + ''.join(cards) + '</div>', unsafe_allow_html=True)
        draft_ids = [d["listing_draft_id"] for d in drafts]
        if st.session_state.get("ai_selected_draft") not in draft_ids:
            st.session_state["ai_selected_draft"] = draft_ids[0]
        chosen = st.selectbox("編集する下書き", draft_ids, format_func=lambda value: next(
            f"{d['title'] or '未生成'} / {d['status']} / {value}" for d in drafts if d["listing_draft_id"] == value), key="ai_selected_draft")
        _editor(service, service.get(chosen), actor, calculate_expected)
