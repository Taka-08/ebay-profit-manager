from __future__ import annotations

import csv
import io
import sqlite3
from datetime import datetime
from pathlib import Path

import streamlit as st


DB_PATH = Path(__file__).with_name("ebay_research.sqlite3")
DEFAULT_EXCHANGE_RATE = 160.0
SORT_OPTIONS = (
    "おすすめ度が高い順",
    "予想利益が高い順",
    "ROIが高い順",
    "売れた個数が多い順",
    "ライバルが少ない順",
)
TEXT_COLUMNS = {
    "id": "ID",
    "product_name": "商品名",
    "keyword": "検索キーワード",
    "ebay_price_usd": "eBay販売価格（USD）",
    "sold_count": "売れた個数",
    "competitor_count": "ライバル出品数",
    "purchase_price_yen": "仕入れ価格（円）",
    "shipping_yen": "想定送料（円）",
    "ad_rate": "広告費率（%）",
    "ebay_fee_rate": "eBay手数料率（%）",
    "exchange_rate": "為替レート",
    "expected_profit_yen": "予想利益（円）",
    "profit_margin": "利益率（%）",
    "roi": "ROI（%）",
    "monthly_sales": "月間販売数",
    "sell_through": "ライバル数に対する売れ行き",
    "recommendation_score": "おすすめ度スコア",
    "memo": "メモ",
    "source": "登録方法",
    "created_at": "登録日時",
    "updated_at": "更新日時",
}
CSV_ALIASES = {
    "product_name": ("商品名", "product_name", "name", "title"),
    "keyword": ("検索キーワード", "keyword", "search_keyword"),
    "ebay_price_usd": ("eBay販売価格（USD）", "ebay_price_usd", "price_usd", "price"),
    "sold_count": ("売れた個数", "sold_count", "sold", "sales_count"),
    "competitor_count": ("ライバル出品数", "competitor_count", "competitors", "active_listings"),
    "purchase_price_yen": ("仕入れ価格（円）", "purchase_price_yen", "purchase_yen", "cost_yen"),
    "shipping_yen": ("想定送料（円）", "shipping_yen", "shipping_cost_yen"),
    "ad_rate": ("広告費率", "広告費率（%）", "ad_rate", "ad_rate_percent"),
    "ebay_fee_rate": ("eBay手数料率", "eBay手数料率（%）", "ebay_fee_rate", "fee_rate"),
    "exchange_rate": ("為替レート", "exchange_rate", "usd_jpy"),
    "memo": ("メモ", "memo", "note"),
}


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS research_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT NOT NULL,
                keyword TEXT NOT NULL DEFAULT '',
                ebay_price_usd REAL NOT NULL DEFAULT 0,
                sold_count REAL NOT NULL DEFAULT 0,
                competitor_count REAL NOT NULL DEFAULT 0,
                purchase_price_yen REAL NOT NULL DEFAULT 0,
                shipping_yen REAL NOT NULL DEFAULT 0,
                ad_rate REAL NOT NULL DEFAULT 0,
                ebay_fee_rate REAL NOT NULL DEFAULT 13.25,
                exchange_rate REAL NOT NULL DEFAULT 160,
                memo TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def to_float(value: object, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return default


def calculate_metrics(row: dict[str, object]) -> dict[str, float]:
    gross_sales_yen = to_float(row.get("ebay_price_usd")) * to_float(row.get("exchange_rate"), DEFAULT_EXCHANGE_RATE)
    ebay_fee_yen = gross_sales_yen * to_float(row.get("ebay_fee_rate")) / 100
    ad_fee_yen = gross_sales_yen * to_float(row.get("ad_rate")) / 100
    product_cost_yen = to_float(row.get("purchase_price_yen")) + to_float(row.get("shipping_yen"))
    expected_profit_yen = gross_sales_yen - product_cost_yen - ebay_fee_yen - ad_fee_yen
    profit_margin = expected_profit_yen / gross_sales_yen * 100 if gross_sales_yen else 0
    roi = expected_profit_yen / product_cost_yen * 100 if product_cost_yen else 0
    monthly_sales = to_float(row.get("sold_count"))
    competitor_count = to_float(row.get("competitor_count"))
    sell_through = monthly_sales / competitor_count if competitor_count > 0 else monthly_sales
    recommendation_score = calculate_score(expected_profit_yen, roi, monthly_sales, competitor_count, sell_through)
    return {
        "gross_sales_yen": gross_sales_yen,
        "expected_profit_yen": expected_profit_yen,
        "profit_margin": profit_margin,
        "roi": roi,
        "monthly_sales": monthly_sales,
        "sell_through": sell_through,
        "recommendation_score": recommendation_score,
    }


def calculate_score(
    expected_profit_yen: float,
    roi: float,
    monthly_sales: float,
    competitor_count: float,
    sell_through: float,
) -> float:
    profit_points = min(max(expected_profit_yen, 0) / 3000 * 30, 30)
    roi_points = min(max(roi, 0) / 100 * 25, 25)
    sales_points = min(max(monthly_sales, 0) / 50 * 25, 25)
    demand_points = min(max(sell_through, 0) / 2 * 10, 10)
    competition_points = max(0, 10 - min(competitor_count, 100) / 10)
    return round(profit_points + roi_points + sales_points + demand_points + competition_points, 1)


def fetch_items() -> list[dict[str, object]]:
    init_db()
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM research_items
            ORDER BY updated_at DESC, id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def save_item(values: dict[str, object], item_id: int | None = None, source: str = "manual") -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "product_name": str(values.get("product_name", "")).strip(),
        "keyword": str(values.get("keyword", "")).strip(),
        "ebay_price_usd": to_float(values.get("ebay_price_usd")),
        "sold_count": to_float(values.get("sold_count")),
        "competitor_count": to_float(values.get("competitor_count")),
        "purchase_price_yen": to_float(values.get("purchase_price_yen")),
        "shipping_yen": to_float(values.get("shipping_yen")),
        "ad_rate": to_float(values.get("ad_rate")),
        "ebay_fee_rate": to_float(values.get("ebay_fee_rate"), 13.25),
        "exchange_rate": to_float(values.get("exchange_rate"), DEFAULT_EXCHANGE_RATE),
        "memo": str(values.get("memo", "")).strip(),
        "source": source,
    }
    if not payload["product_name"]:
        raise ValueError("商品名は必須です。")

    with get_connection() as connection:
        if item_id is None:
            connection.execute(
                """
                INSERT INTO research_items (
                    product_name, keyword, ebay_price_usd, sold_count, competitor_count,
                    purchase_price_yen, shipping_yen, ad_rate, ebay_fee_rate, exchange_rate,
                    memo, source, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["product_name"],
                    payload["keyword"],
                    payload["ebay_price_usd"],
                    payload["sold_count"],
                    payload["competitor_count"],
                    payload["purchase_price_yen"],
                    payload["shipping_yen"],
                    payload["ad_rate"],
                    payload["ebay_fee_rate"],
                    payload["exchange_rate"],
                    payload["memo"],
                    payload["source"],
                    now,
                    now,
                ),
            )
        else:
            connection.execute(
                """
                UPDATE research_items
                SET product_name = ?,
                    keyword = ?,
                    ebay_price_usd = ?,
                    sold_count = ?,
                    competitor_count = ?,
                    purchase_price_yen = ?,
                    shipping_yen = ?,
                    ad_rate = ?,
                    ebay_fee_rate = ?,
                    exchange_rate = ?,
                    memo = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    payload["product_name"],
                    payload["keyword"],
                    payload["ebay_price_usd"],
                    payload["sold_count"],
                    payload["competitor_count"],
                    payload["purchase_price_yen"],
                    payload["shipping_yen"],
                    payload["ad_rate"],
                    payload["ebay_fee_rate"],
                    payload["exchange_rate"],
                    payload["memo"],
                    now,
                    item_id,
                ),
            )


def delete_item(item_id: int) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM research_items WHERE id = ?", (item_id,))


def row_with_metrics(row: dict[str, object]) -> dict[str, object]:
    result = dict(row)
    result.update(calculate_metrics(result))
    return result


def display_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    formatted = []
    for source in rows:
        row = row_with_metrics(source)
        formatted.append(
            {
                TEXT_COLUMNS["id"]: row["id"],
                TEXT_COLUMNS["product_name"]: row["product_name"],
                TEXT_COLUMNS["keyword"]: row["keyword"],
                TEXT_COLUMNS["ebay_price_usd"]: row["ebay_price_usd"],
                TEXT_COLUMNS["sold_count"]: row["sold_count"],
                TEXT_COLUMNS["competitor_count"]: row["competitor_count"],
                TEXT_COLUMNS["purchase_price_yen"]: row["purchase_price_yen"],
                TEXT_COLUMNS["shipping_yen"]: row["shipping_yen"],
                TEXT_COLUMNS["expected_profit_yen"]: row["expected_profit_yen"],
                TEXT_COLUMNS["profit_margin"]: row["profit_margin"],
                TEXT_COLUMNS["roi"]: row["roi"],
                TEXT_COLUMNS["monthly_sales"]: row["monthly_sales"],
                TEXT_COLUMNS["sell_through"]: row["sell_through"],
                TEXT_COLUMNS["recommendation_score"]: row["recommendation_score"],
                TEXT_COLUMNS["memo"]: row["memo"],
                TEXT_COLUMNS["updated_at"]: row["updated_at"],
            }
        )
    return formatted


def csv_text(rows: list[dict[str, object]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(TEXT_COLUMNS.values()), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        enriched = row_with_metrics(row)
        writer.writerow(
            {
                TEXT_COLUMNS["id"]: enriched["id"],
                TEXT_COLUMNS["product_name"]: enriched["product_name"],
                TEXT_COLUMNS["keyword"]: enriched["keyword"],
                TEXT_COLUMNS["ebay_price_usd"]: enriched["ebay_price_usd"],
                TEXT_COLUMNS["sold_count"]: enriched["sold_count"],
                TEXT_COLUMNS["competitor_count"]: enriched["competitor_count"],
                TEXT_COLUMNS["purchase_price_yen"]: enriched["purchase_price_yen"],
                TEXT_COLUMNS["shipping_yen"]: enriched["shipping_yen"],
                TEXT_COLUMNS["ad_rate"]: enriched["ad_rate"],
                TEXT_COLUMNS["ebay_fee_rate"]: enriched["ebay_fee_rate"],
                TEXT_COLUMNS["exchange_rate"]: enriched["exchange_rate"],
                TEXT_COLUMNS["expected_profit_yen"]: enriched["expected_profit_yen"],
                TEXT_COLUMNS["profit_margin"]: enriched["profit_margin"],
                TEXT_COLUMNS["roi"]: enriched["roi"],
                TEXT_COLUMNS["monthly_sales"]: enriched["monthly_sales"],
                TEXT_COLUMNS["sell_through"]: enriched["sell_through"],
                TEXT_COLUMNS["recommendation_score"]: enriched["recommendation_score"],
                TEXT_COLUMNS["memo"]: enriched["memo"],
                TEXT_COLUMNS["source"]: enriched["source"],
                TEXT_COLUMNS["created_at"]: enriched["created_at"],
                TEXT_COLUMNS["updated_at"]: enriched["updated_at"],
            }
        )
    return output.getvalue()


def csv_template() -> str:
    output = io.StringIO()
    fieldnames = [
        "商品名",
        "検索キーワード",
        "eBay販売価格（USD）",
        "売れた個数",
        "ライバル出品数",
        "仕入れ価格（円）",
        "想定送料（円）",
        "広告費率（%）",
        "eBay手数料率（%）",
        "為替レート",
        "メモ",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerow(
        {
            "商品名": "Pokemon card lot",
            "検索キーワード": "Pokemon",
            "eBay販売価格（USD）": 29.99,
            "売れた個数": 35,
            "ライバル出品数": 80,
            "仕入れ価格（円）": 1800,
            "想定送料（円）": 1200,
            "広告費率（%）": 2,
            "eBay手数料率（%）": 13.25,
            "為替レート": 160,
            "メモ": "CSV登録サンプル",
        }
    )
    return output.getvalue()


def find_csv_value(row: dict[str, str], key: str) -> str:
    for alias in CSV_ALIASES[key]:
        if alias in row:
            return row.get(alias, "")
    return ""


def import_csv(uploaded_file) -> tuple[int, list[str]]:
    text = uploaded_file.getvalue().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    imported = 0
    errors = []
    for line_no, row in enumerate(reader, start=2):
        values = {key: find_csv_value(row, key) for key in CSV_ALIASES}
        try:
            save_item(values, source="csv")
            imported += 1
        except ValueError as error:
            errors.append(f"{line_no}行目: {error}")
    return imported, errors


def sort_rows(rows: list[dict[str, object]], sort_option: str) -> list[dict[str, object]]:
    enriched = [row_with_metrics(row) for row in rows]
    if sort_option == "予想利益が高い順":
        return sorted(enriched, key=lambda row: row["expected_profit_yen"], reverse=True)
    if sort_option == "ROIが高い順":
        return sorted(enriched, key=lambda row: row["roi"], reverse=True)
    if sort_option == "売れた個数が多い順":
        return sorted(enriched, key=lambda row: row["sold_count"], reverse=True)
    if sort_option == "ライバルが少ない順":
        return sorted(enriched, key=lambda row: row["competitor_count"])
    return sorted(enriched, key=lambda row: row["recommendation_score"], reverse=True)


def apply_filters(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    keywords = sorted({str(row.get("keyword", "")).strip() for row in rows if str(row.get("keyword", "")).strip()})
    col1, col2, col3, col4, col5 = st.columns(5)
    min_profit = col1.checkbox("利益500円以上")
    min_roi = col2.checkbox("ROI50%以上")
    min_sales = col3.checkbox("月30個以上売れている")
    low_competition = col4.checkbox("ライバル50件以下")
    keyword_filter = col5.selectbox("キーワード別", ("すべて", *keywords))

    filtered = []
    for row in rows:
        enriched = row_with_metrics(row)
        if min_profit and enriched["expected_profit_yen"] < 500:
            continue
        if min_roi and enriched["roi"] < 50:
            continue
        if min_sales and enriched["monthly_sales"] < 30:
            continue
        if low_competition and enriched["competitor_count"] > 50:
            continue
        if keyword_filter != "すべて" and enriched["keyword"] != keyword_filter:
            continue
        filtered.append(enriched)
    return filtered


def render_dashboard(rows: list[dict[str, object]]) -> None:
    st.subheader("ダッシュボード")
    enriched = [row_with_metrics(row) for row in rows]
    total_count = len(enriched)
    profitable_count = sum(1 for row in enriched if row["expected_profit_yen"] >= 500)
    average_profit = sum(row["expected_profit_yen"] for row in enriched) / total_count if total_count else 0
    best_score = max((row["recommendation_score"] for row in enriched), default=0)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("登録件数", f"{total_count:,}")
    col2.metric("利益500円以上", f"{profitable_count:,}")
    col3.metric("平均予想利益", f"{average_profit:,.0f} 円")
    col4.metric("最高おすすめ度", f"{best_score:.1f}")


def render_registration() -> None:
    st.subheader("リサーチ登録")
    with st.form("research_registration_form"):
        col1, col2 = st.columns(2)
        product_name = col1.text_input("商品名")
        keyword = col2.text_input("検索キーワード", placeholder="例: Pokemon, UNIQLO, Sanrio")
        col3, col4, col5 = st.columns(3)
        ebay_price_usd = col3.number_input("eBay販売価格（USD）", min_value=0.0, value=29.99, step=1.0, format="%.2f")
        sold_count = col4.number_input("売れた個数", min_value=0.0, value=0.0, step=1.0, format="%.0f")
        competitor_count = col5.number_input("ライバル出品数", min_value=0.0, value=0.0, step=1.0, format="%.0f")
        col6, col7, col8, col9 = st.columns(4)
        purchase_price_yen = col6.number_input("仕入れ価格（円）", min_value=0.0, value=0.0, step=100.0, format="%.0f")
        shipping_yen = col7.number_input("想定送料（円）", min_value=0.0, value=0.0, step=100.0, format="%.0f")
        ad_rate = col8.number_input("広告費率（%）", min_value=0.0, value=2.0, step=0.5, format="%.2f")
        ebay_fee_rate = col9.number_input("eBay手数料率（%）", min_value=0.0, value=13.25, step=0.25, format="%.2f")
        exchange_rate = st.number_input("為替レート", min_value=0.01, value=DEFAULT_EXCHANGE_RATE, step=0.1, format="%.2f")
        memo = st.text_area("メモ")
        submitted = st.form_submit_button("登録")

    if submitted:
        try:
            save_item(
                {
                    "product_name": product_name,
                    "keyword": keyword,
                    "ebay_price_usd": ebay_price_usd,
                    "sold_count": sold_count,
                    "competitor_count": competitor_count,
                    "purchase_price_yen": purchase_price_yen,
                    "shipping_yen": shipping_yen,
                    "ad_rate": ad_rate,
                    "ebay_fee_rate": ebay_fee_rate,
                    "exchange_rate": exchange_rate,
                    "memo": memo,
                }
            )
            st.success("リサーチ結果を登録しました。")
            st.rerun()
        except ValueError as error:
            st.error(str(error))

    st.write("CSV登録")
    upload_col, template_col = st.columns([2, 1])
    uploaded_file = upload_col.file_uploader("CSVファイルを選択", type=["csv"])
    template_col.download_button(
        "CSVテンプレートをダウンロード",
        csv_template().encode("utf-8-sig"),
        file_name="ebay_research_template.csv",
        mime="text/csv",
    )
    if uploaded_file and st.button("CSVを登録"):
        imported, errors = import_csv(uploaded_file)
        if imported:
            st.success(f"{imported}件を登録しました。")
        for error in errors:
            st.warning(error)
        st.rerun()


def render_ranking(rows: list[dict[str, object]]) -> None:
    st.subheader("おすすめ商品ランキング")
    sort_option = st.selectbox("並び替え", SORT_OPTIONS)
    ranked_rows = sort_rows(rows, sort_option)
    st.dataframe(
        display_rows(ranked_rows),
        hide_index=True,
        use_container_width=True,
        column_config=column_config(),
    )


def column_config() -> dict[str, object]:
    return {
        TEXT_COLUMNS["product_name"]: st.column_config.TextColumn(width="large"),
        TEXT_COLUMNS["keyword"]: st.column_config.TextColumn(width="small"),
        TEXT_COLUMNS["ebay_price_usd"]: st.column_config.NumberColumn(format="$%.2f", width="small"),
        TEXT_COLUMNS["sold_count"]: st.column_config.NumberColumn(format="%.0f", width="small"),
        TEXT_COLUMNS["competitor_count"]: st.column_config.NumberColumn(format="%.0f", width="small"),
        TEXT_COLUMNS["purchase_price_yen"]: st.column_config.NumberColumn(format="%.0f 円", width="small"),
        TEXT_COLUMNS["shipping_yen"]: st.column_config.NumberColumn(format="%.0f 円", width="small"),
        TEXT_COLUMNS["expected_profit_yen"]: st.column_config.NumberColumn(format="%.0f 円", width="small"),
        TEXT_COLUMNS["profit_margin"]: st.column_config.NumberColumn(format="%.1f%%", width="small"),
        TEXT_COLUMNS["roi"]: st.column_config.NumberColumn(format="%.1f%%", width="small"),
        TEXT_COLUMNS["monthly_sales"]: st.column_config.NumberColumn(format="%.0f", width="small"),
        TEXT_COLUMNS["sell_through"]: st.column_config.NumberColumn(format="%.2f", width="small"),
        TEXT_COLUMNS["recommendation_score"]: st.column_config.NumberColumn(format="%.1f", width="small"),
    }


def render_list(rows: list[dict[str, object]]) -> None:
    st.subheader("リサーチ一覧")
    filtered_rows = apply_filters(rows)
    st.dataframe(
        display_rows(filtered_rows),
        hide_index=True,
        use_container_width=True,
        column_config=column_config(),
    )
    st.caption(f"表示件数: {len(filtered_rows)} / 保存件数: {len(rows)}")

    if not rows:
        return
    st.write("保存データの編集・削除")
    labels = {int(row["id"]): f"#{row['id']} - {row['product_name']} / {row.get('keyword', '')}" for row in rows}
    selected_id = st.selectbox(
        "編集するデータ",
        options=list(labels.keys()),
        format_func=lambda item_id: labels[int(item_id)],
    )
    selected = next(row for row in rows if int(row["id"]) == int(selected_id))

    with st.form(f"edit_research_{selected_id}"):
        col1, col2 = st.columns(2)
        product_name = col1.text_input("商品名", value=str(selected["product_name"]))
        keyword = col2.text_input("検索キーワード", value=str(selected["keyword"]))
        col3, col4, col5 = st.columns(3)
        ebay_price_usd = col3.number_input(
            "eBay販売価格（USD）",
            min_value=0.0,
            value=float(selected["ebay_price_usd"]),
            step=1.0,
            format="%.2f",
        )
        sold_count = col4.number_input("売れた個数", min_value=0.0, value=float(selected["sold_count"]), step=1.0)
        competitor_count = col5.number_input(
            "ライバル出品数",
            min_value=0.0,
            value=float(selected["competitor_count"]),
            step=1.0,
        )
        col6, col7, col8, col9 = st.columns(4)
        purchase_price_yen = col6.number_input(
            "仕入れ価格（円）",
            min_value=0.0,
            value=float(selected["purchase_price_yen"]),
            step=100.0,
        )
        shipping_yen = col7.number_input("想定送料（円）", min_value=0.0, value=float(selected["shipping_yen"]), step=100.0)
        ad_rate = col8.number_input("広告費率（%）", min_value=0.0, value=float(selected["ad_rate"]), step=0.5)
        ebay_fee_rate = col9.number_input(
            "eBay手数料率（%）",
            min_value=0.0,
            value=float(selected["ebay_fee_rate"]),
            step=0.25,
        )
        exchange_rate = st.number_input(
            "為替レート",
            min_value=0.01,
            value=float(selected["exchange_rate"]),
            step=0.1,
            format="%.2f",
        )
        memo = st.text_area("メモ", value=str(selected["memo"]))
        save_col, delete_col = st.columns(2)
        update = save_col.form_submit_button("保存")
        delete = delete_col.form_submit_button("削除")

    if update:
        try:
            save_item(
                {
                    "product_name": product_name,
                    "keyword": keyword,
                    "ebay_price_usd": ebay_price_usd,
                    "sold_count": sold_count,
                    "competitor_count": competitor_count,
                    "purchase_price_yen": purchase_price_yen,
                    "shipping_yen": shipping_yen,
                    "ad_rate": ad_rate,
                    "ebay_fee_rate": ebay_fee_rate,
                    "exchange_rate": exchange_rate,
                    "memo": memo,
                },
                item_id=int(selected_id),
            )
            st.success("保存しました。")
            st.rerun()
        except ValueError as error:
            st.error(str(error))

    if delete:
        delete_item(int(selected_id))
        st.success("削除しました。")
        st.rerun()


def render_csv_export(rows: list[dict[str, object]]) -> None:
    st.subheader("CSV出力")
    st.download_button(
        "リサーチ結果をCSVでダウンロード",
        csv_text(rows).encode("utf-8-sig"),
        file_name="ebay_research_results.csv",
        mime="text/csv",
        disabled=not rows,
    )


def main() -> None:
    st.set_page_config(page_title="eBayリサーチツール", page_icon="🔎", layout="wide")
    init_db()
    st.title("eBayリサーチツール")
    st.caption("手入力・CSV登録ベースで、利益が出そうな商品候補を管理します。")

    rows = fetch_items()
    render_dashboard(rows)
    tabs = st.tabs(("リサーチ登録", "リサーチ一覧", "おすすめ商品ランキング", "CSV出力"))
    with tabs[0]:
        render_registration()
    with tabs[1]:
        render_list(rows)
    with tabs[2]:
        render_ranking(rows)
    with tabs[3]:
        render_csv_export(rows)

    st.caption(f"保存先SQLite: {DB_PATH}")


if __name__ == "__main__":
    main()
