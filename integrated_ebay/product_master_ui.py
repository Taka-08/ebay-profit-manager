"""Streamlit UI for the Stage 3 product master and inventory foundation."""

from __future__ import annotations

import html
import os
from typing import Any
from urllib.parse import urlencode

import streamlit as st

from .services import (
    PRODUCT_STATUSES,
    PURCHASE_CURRENCIES,
    STOCK_MODES,
    ProductCatalogService,
)


SOURCE_TYPES = (
    "AMAZON", "RAKUTEN", "YAHOO_SHOPPING", "YAHOO_AUCTIONS",
    "MERCARI", "PHYSICAL_STORE", "MANUFACTURER", "WHOLESALE", "OTHER_EC",
)
STOCK_STATUSES = ("UNKNOWN", "IN_STOCK", "OUT_OF_STOCK", "LIMITED")
DEFAULT_PROFIT_CALCULATOR_URL = (
    "https://ebay-profit-manager-va8o3qebvuowbhtljcdjw8.streamlit.app/"
)


def _profit_calculator_url() -> str:
    configured = os.environ.get("PROFIT_CALCULATOR_URL", "").strip()
    if configured:
        return configured
    try:
        section = st.secrets.get("app_urls", {})
        if hasattr(section, "get"):
            configured = str(section.get("profit_calculator", "")).strip()
    except Exception:
        configured = ""
    return configured or DEFAULT_PROFIT_CALCULATOR_URL


def _product_fields(container: Any, values: dict[str, Any], key: str) -> dict[str, Any]:
    row1 = container.columns(3)
    product_name = row1[0].text_input(
        "商品名", value=str(values.get("product_name") or ""), key=f"{key}_name"
    )
    sku = row1[1].text_input("SKU", value=str(values.get("sku") or ""), key=f"{key}_sku")
    platform = row1[2].selectbox(
        "主な販売先", ("eBay", "メルカリ", "iPhone転売"),
        index=("eBay", "メルカリ", "iPhone転売").index(
            str(values.get("platform") or "eBay")
            if str(values.get("platform") or "eBay") in ("eBay", "メルカリ", "iPhone転売")
            else "eBay"
        ), key=f"{key}_platform",
    )
    row2 = container.columns(3)
    jan = row2[0].text_input("JAN", value=str(values.get("jan") or ""), key=f"{key}_jan")
    ean = row2[1].text_input("EAN", value=str(values.get("ean") or ""), key=f"{key}_ean")
    upc = row2[2].text_input("UPC", value=str(values.get("upc") or ""), key=f"{key}_upc")
    row3 = container.columns(3)
    brand = row3[0].text_input("ブランド", value=str(values.get("brand") or ""), key=f"{key}_brand")
    model_number = row3[1].text_input(
        "型番", value=str(values.get("model_number") or ""), key=f"{key}_model"
    )
    category = row3[2].text_input(
        "カテゴリ", value=str(values.get("category") or ""), key=f"{key}_category"
    )
    row4 = container.columns(3)
    purchase_price = row4[0].number_input(
        "仕入価格", min_value=0.0, value=float(values.get("purchase_price") or 0),
        step=100.0, key=f"{key}_purchase_price",
    )
    current_currency = str(values.get("purchase_currency") or "JPY").upper()
    if current_currency not in PURCHASE_CURRENCIES:
        current_currency = "JPY"
    purchase_currency = row4[1].selectbox(
        "仕入通貨", PURCHASE_CURRENCIES,
        index=PURCHASE_CURRENCIES.index(current_currency), key=f"{key}_currency",
    )
    status_value = str(values.get("status") or "ACTIVE").upper()
    if status_value not in PRODUCT_STATUSES:
        status_value = "ACTIVE"
    status = row4[2].selectbox(
        "商品ステータス", PRODUCT_STATUSES,
        index=PRODUCT_STATUSES.index(status_value), key=f"{key}_status",
    )
    row5 = container.columns(3)
    country_of_origin = row5[0].text_input(
        "原産国（ISO2推奨）", value=str(values.get("country_of_origin") or ""),
        key=f"{key}_origin",
    )
    hs_code = row5[1].text_input(
        "HSコード", value=str(values.get("hs_code") or ""), key=f"{key}_hs"
    )
    hts_code = row5[2].text_input(
        "HTSコード", value=str(values.get("hts_code") or ""), key=f"{key}_hts"
    )
    row6 = container.columns(4)
    weight_g = row6[0].number_input(
        "重量（g）", min_value=0.0, value=float(values.get("weight_g") or 0),
        step=10.0, key=f"{key}_weight",
    )
    length_cm = row6[1].number_input(
        "長さ（cm）", min_value=0.0, value=float(values.get("length_cm") or 0),
        step=0.1, key=f"{key}_length",
    )
    width_cm = row6[2].number_input(
        "幅（cm）", min_value=0.0, value=float(values.get("width_cm") or 0),
        step=0.1, key=f"{key}_width",
    )
    height_cm = row6[3].number_input(
        "高さ（cm）", min_value=0.0, value=float(values.get("height_cm") or 0),
        step=0.1, key=f"{key}_height",
    )
    notes = container.text_area(
        "メモ", value=str(values.get("notes") or ""), key=f"{key}_notes"
    )
    return {
        "product_name": product_name, "sku": sku, "platform": platform,
        "jan": jan, "ean": ean, "upc": upc, "brand": brand,
        "model_number": model_number, "category": category, "notes": notes,
        "country_of_origin": country_of_origin, "hs_code": hs_code,
        "hts_code": hts_code, "weight_g": weight_g, "length_cm": length_cm,
        "width_cm": width_cm, "height_cm": height_cm,
        "purchase_price": purchase_price, "purchase_currency": purchase_currency,
        "status": status,
    }


def _show_duplicate_warning(service: ProductCatalogService, values: dict[str, Any], exclude: str | None = None) -> None:
    candidates = service.duplicate_candidates(values, exclude_product_id=exclude)
    if candidates:
        labels = ", ".join(
            f"{item['product_name']} ({item['product_id']})" for item in candidates[:5]
        )
        st.warning(f"重複候補があります。自動統合はしていません: {labels}")


def _render_create(service: ProductCatalogService) -> None:
    with st.expander("商品を新規作成", expanded=False):
        with st.form("product_master_create"):
            values = _product_fields(st, {}, "new_product")
            submitted = st.form_submit_button("商品を登録", type="primary", use_container_width=True)
        if submitted:
            try:
                _show_duplicate_warning(service, values)
                product_id = service.create_product(values)
                st.session_state.product_master_selected_id = product_id
                st.success(f"商品を登録しました: {product_id}")
                st.rerun()
            except (ValueError, RuntimeError) as exc:
                st.error(f"商品を登録できませんでした: {exc}")


def _render_inventory(service: ProductCatalogService, product: dict[str, Any]) -> None:
    inventory = product.get("inventory") or {}
    with st.expander("在庫", expanded=True):
        with st.form(f"inventory_{product['product_id']}"):
            columns = st.columns(4)
            mode = str(inventory.get("stock_mode") or "IN_STOCK")
            stock_mode = columns[0].selectbox(
                "在庫方式", STOCK_MODES, index=STOCK_MODES.index(mode),
            )
            on_hand = columns[1].number_input(
                "実在庫", min_value=0, value=int(inventory.get("on_hand_quantity") or 0), step=1,
            )
            reserved = columns[2].number_input(
                "引当数", min_value=0, value=int(inventory.get("reserved_quantity") or 0), step=1,
            )
            reorder = columns[3].number_input(
                "発注点", min_value=0, value=int(inventory.get("reorder_point") or 0), step=1,
            )
            location = st.text_input(
                "保管場所", value=str(inventory.get("storage_location") or "")
            )
            available = product.get("available_quantity")
            st.caption(
                "販売可能数: 仕入先在庫参照予定（DROPSHIP）"
                if available is None else f"販売可能数: {available}"
            )
            submitted = st.form_submit_button("在庫を更新", use_container_width=True)
        if submitted:
            try:
                service.update_inventory(product["product_id"], {
                    "stock_mode": stock_mode, "on_hand_quantity": on_hand,
                    "reserved_quantity": reserved, "reorder_point": reorder,
                    "storage_location": location,
                })
                st.success("在庫を更新しました。")
                st.rerun()
            except ValueError as exc:
                st.error(f"在庫を更新できませんでした: {exc}")


def _source_form_values(prefix: str, source: dict[str, Any] | None = None) -> tuple[dict[str, Any], bool]:
    source = source or {}
    row1 = st.columns(3)
    source_type_value = str(source.get("source_type") or "AMAZON")
    if source_type_value not in SOURCE_TYPES:
        source_type_value = "OTHER_EC"
    source_type = row1[0].selectbox(
        "仕入先種別", SOURCE_TYPES, index=SOURCE_TYPES.index(source_type_value), key=f"{prefix}_type"
    )
    source_name = row1[1].text_input(
        "仕入先名", value=str(source.get("source_name") or ""), key=f"{prefix}_name"
    )
    source_item_id = row1[2].text_input(
        "仕入先商品ID", value=str(source.get("source_item_id") or ""), key=f"{prefix}_item"
    )
    source_url = st.text_input(
        "仕入先URL", value=str(source.get("source_url") or ""), key=f"{prefix}_url"
    )
    row2 = st.columns(4)
    price = row2[0].number_input(
        "価格", min_value=0.0, value=float(source.get("price") or 0), step=100.0,
        key=f"{prefix}_price",
    )
    currency_value = str(source.get("currency") or "JPY")
    currency = row2[1].selectbox(
        "通貨", PURCHASE_CURRENCIES, index=PURCHASE_CURRENCIES.index(currency_value),
        key=f"{prefix}_currency",
    )
    stock_value = str(source.get("stock_status") or "UNKNOWN")
    if stock_value not in STOCK_STATUSES:
        stock_value = "UNKNOWN"
    stock_status = row2[2].selectbox(
        "在庫状態", STOCK_STATUSES, index=STOCK_STATUSES.index(stock_value),
        key=f"{prefix}_stock",
    )
    is_primary = row2[3].checkbox(
        "主仕入先", value=bool(source.get("is_primary")), key=f"{prefix}_primary"
    )
    return {
        "source_type": source_type, "source_name": source_name,
        "source_url": source_url, "source_item_id": source_item_id,
        "price": price, "currency": currency, "stock_status": stock_status,
        "is_primary": is_primary, "last_checked_at": source.get("last_checked_at"),
    }, is_primary


def _render_sources(service: ProductCatalogService, product: dict[str, Any]) -> None:
    with st.expander("仕入先", expanded=False):
        sources = product.get("sources") or []
        if not sources:
            st.info("仕入先はまだ登録されていません。")
        for source in sources:
            marker = "主仕入先" if source.get("is_primary") else "候補"
            with st.expander(f"{source.get('source_name') or source['source_type']} / {marker}"):
                with st.form(f"source_edit_{source['source_id']}"):
                    values, _ = _source_form_values(f"source_{source['source_id']}", source)
                    submitted = st.form_submit_button("仕入先を更新", use_container_width=True)
                if submitted:
                    try:
                        service.update_source(product["product_id"], source["source_id"], values)
                        st.success("仕入先を更新しました。")
                        st.rerun()
                    except ValueError as exc:
                        st.error(f"仕入先を更新できませんでした: {exc}")
        st.markdown("#### 仕入先を追加")
        with st.form(f"source_add_{product['product_id']}"):
            values, _ = _source_form_values(f"source_new_{product['product_id']}")
            submitted = st.form_submit_button("仕入先を追加", use_container_width=True)
        if submitted:
            try:
                service.add_source(product["product_id"], values)
                st.success("仕入先を追加しました。")
                st.rerun()
            except ValueError as exc:
                st.error(f"仕入先を追加できませんでした: {exc}")


def _render_images(service: ProductCatalogService, product: dict[str, Any]) -> None:
    with st.expander("商品画像メタデータ", expanded=False):
        images = product.get("images") or []
        if images:
            st.dataframe(images, use_container_width=True, hide_index=True)
        else:
            st.info("画像情報はまだ登録されていません。")
        st.caption("画像本体はTursoへ保存せず、外部ストレージのURLまたはキーだけを管理します。")
        with st.form(f"image_add_{product['product_id']}"):
            row = st.columns(3)
            provider = row[0].text_input("ストレージ種別", value="external")
            file_name = row[1].text_input("ファイル名")
            sort_order = row[2].number_input("表示順", min_value=0, value=len(images), step=1)
            url = st.text_input("画像URL")
            storage_key = st.text_input("ストレージキー")
            is_primary = st.checkbox("主画像", value=not images)
            submitted = st.form_submit_button("画像情報を登録", use_container_width=True)
        if submitted:
            try:
                service.add_image(product["product_id"], {
                    "storage_provider": provider, "file_name": file_name,
                    "sort_order": sort_order, "url": url,
                    "storage_key": storage_key, "is_primary": is_primary,
                })
                st.success("画像情報を登録しました。")
                st.rerun()
            except ValueError as exc:
                st.error(f"画像情報を登録できませんでした: {exc}")


def _render_detail(service: ProductCatalogService, product_id: str, on_create_draft=None) -> None:
    product = service.get_product(product_id)
    if product is None:
        st.error("商品が見つかりません。")
        return
    st.markdown(f"### {product['product_name']}")
    st.caption(f"product_id: {product_id}")
    profit_url = _profit_calculator_url().rstrip("/") + "/?" + urlencode({"product_id": product_id})
    st.link_button("この商品で利益計算", profit_url, use_container_width=True)
    if on_create_draft is not None:
        st.button("AI出品下書きを作成", key=f"product_draft_{product_id}",
                  on_click=on_create_draft, args=(product_id,), use_container_width=True)
    with st.expander("商品情報を編集", expanded=True):
        with st.form(f"product_edit_{product_id}"):
            values = _product_fields(st, product, f"edit_{product_id}")
            submitted = st.form_submit_button("商品情報を保存", type="primary", use_container_width=True)
        if submitted:
            try:
                _show_duplicate_warning(service, values, product_id)
                service.update_product(product_id, values)
                st.success("商品情報を更新しました。")
                st.rerun()
            except ValueError as exc:
                st.error(f"商品情報を更新できませんでした: {exc}")
    _render_inventory(service, product)
    _render_sources(service, product)
    _render_images(service, product)
    with st.expander("関連する出品", expanded=False):
        listings = product.get("listings") or []
        if listings:
            st.dataframe(listings, use_container_width=True, hide_index=True)
        else:
            st.info("出品なし")
    if str(product.get("status") or "").upper() != "ARCHIVED":
        with st.expander("商品をアーカイブ", expanded=False):
            st.warning("商品は物理削除せず、ARCHIVEDとして残します。")
            if st.button("アーカイブする", key=f"archive_{product_id}", use_container_width=True):
                service.archive_product(product_id)
                st.success("商品をアーカイブしました。")
                st.rerun()


def render_product_master(connection_factory: Any, on_create_draft=None) -> None:
    st.markdown(
        """
        <style>
        .product-master-mobile-list { display: none; }
        .product-master-mobile-card {
          border: 1px solid color-mix(in srgb, currentColor 22%, transparent);
          border-radius: 8px;
          margin: 0 0 10px;
          padding: 12px;
        }
        .product-master-mobile-card strong { display: block; margin-bottom: 4px; }
        .product-master-mobile-meta { font-size: 0.88rem; line-height: 1.55; }
        @media (max-width: 768px) {
          div[data-testid="stForm"] button,
          div[data-testid="stLinkButton"] a { width: 100% !important; min-height: 46px; }
          .st-key-product_master_desktop_list { display: none; }
          .product-master-mobile-list { display: block; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.header("商品マスター")
    st.caption("商品・複数仕入先・在庫・画像情報をproduct_idで一元管理します。")
    service = ProductCatalogService(connection_factory)
    _render_create(service)
    filter_columns = st.columns([2, 1])
    search = filter_columns[0].text_input(
        "商品を検索", placeholder="商品名、SKU、JAN/EAN/UPC、ブランド、型番"
    )
    status = filter_columns[1].selectbox("ステータス", ("ALL", *PRODUCT_STATUSES))
    products = service.list_products(search=search, status=status)
    st.caption(f"{len(products)}件")
    if not products:
        st.info("条件に一致する商品がありません。")
        return
    with st.container(key="product_master_desktop_list"):
        st.dataframe(
            [
                {
                    "商品名": item.get("product_name"), "SKU": item.get("sku"),
                    "ブランド": item.get("brand"), "型番": item.get("model_number"),
                    "仕入価格": item.get("purchase_price"),
                    "通貨": item.get("purchase_currency"), "状態": item.get("status"),
                    "product_id": item.get("product_id"),
                }
                for item in products
            ],
            use_container_width=True,
            hide_index=True,
        )
    mobile_cards = []
    for item in products:
        product_name = html.escape(str(item.get("product_name") or "（商品名なし）"))
        sku = html.escape(str(item.get("sku") or "未設定"))
        brand = html.escape(str(item.get("brand") or "未設定"))
        model = html.escape(str(item.get("model_number") or "未設定"))
        status_label = html.escape(str(item.get("status") or "ACTIVE"))
        product_id_label = html.escape(str(item.get("product_id") or ""))
        mobile_cards.append(
            '<div class="product-master-mobile-card">'
            f"<strong>{product_name}</strong>"
            '<div class="product-master-mobile-meta">'
            f"SKU: {sku}<br>ブランド / 型番: {brand} / {model}<br>"
            f"状態: {status_label}<br>product_id: {product_id_label}"
            "</div></div>"
        )
    st.markdown(
        '<div class="product-master-mobile-list">' + "".join(mobile_cards) + "</div>",
        unsafe_allow_html=True,
    )
    option_ids = [str(item["product_id"]) for item in products]
    selected = st.session_state.get("product_master_selected_id")
    if selected not in option_ids:
        selected = option_ids[0]
    selected_id = st.selectbox(
        "詳細を表示する商品", option_ids, index=option_ids.index(selected),
        format_func=lambda value: next(
            f"{item['product_name']} / {item.get('sku') or 'SKUなし'}"
            for item in products if item["product_id"] == value
        ),
        key="product_master_selected_id",
    )
    _render_detail(service, selected_id, on_create_draft)
