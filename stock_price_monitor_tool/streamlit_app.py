from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import streamlit as st


DB_PATH = Path(__file__).with_name("stock_monitor.sqlite3")

SOURCE_SITES = ("メルカリ", "Amazon", "楽天", "Yahoo!ショッピング", "Yahoo!フリマ", "ラクマ", "その他")
STATUS_MONITORING = "監視中"
STATUS_SOLD_OUT = "売り切れ"
STATUS_PRICE_CHANGED = "価格変更あり"
STATUS_PAUSED = "停止中"
STATUS_OPTIONS = (
    STATUS_MONITORING,
    STATUS_SOLD_OUT,
    STATUS_PRICE_CHANGED,
    STATUS_PAUSED,
)
STOCK_AVAILABLE = "在庫あり"
STOCK_SOLD_OUT = "売り切れ"
STOCK_NEEDS_CHECK = "確認が必要"
CHECK_PAGE_MISSING = "商品ページなし"
RESULT_PRICE_UP = "価格上昇"
RESULT_PRICE_DOWN = "価格下落"
RESULT_PRICE_SAME = "価格変化なし"
RESULT_NEEDS_CHECK = "確認が必要"
RESULT_SOLD_OUT = "売り切れ"
RESULT_RELISTED = "再出品"
ALERT_RESULTS = (RESULT_SOLD_OUT, RESULT_RELISTED, RESULT_PRICE_UP, RESULT_PRICE_DOWN)
DISCORD_WEBHOOK_SETTING_KEY = "discord_webhook_url"
AUTO_MONITOR_ENABLED_KEY = "auto_monitor_enabled"
AUTO_MONITOR_INTERVAL_KEY = "auto_monitor_interval_minutes"
AUTO_MONITOR_STARTED_AT_KEY = "auto_monitor_started_at"
AUTO_MONITOR_LAST_RUN_AT_KEY = "auto_monitor_last_run_at"
MONITOR_INTERVAL_OPTIONS = (1, 5, 10, 30, 60)

SOLD_OUT_KEYWORDS = (
    "売り切れ",
    "売切れ",
    "sold out",
    "currently unavailable",
    "在庫切れ",
    "品切れ",
    "out of stock",
)
PRICE_PATTERNS = (
    r"￥\s*([0-9,]+)",
    r"¥\s*([0-9,]+)",
    r'"price"\s*:\s*"?([0-9,]+)',
    r"data-price\s*=\s*\"([0-9,]+)\"",
)


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS monitor_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT NOT NULL,
                source_site TEXT NOT NULL,
                source_url TEXT NOT NULL,
                current_purchase_price REAL NOT NULL DEFAULT 0,
                last_checked_price REAL,
                ebay_listing_price REAL NOT NULL DEFAULT 0,
                expected_shipping_yen REAL NOT NULL DEFAULT 0,
                memo TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '監視中',
                last_stock_state TEXT NOT NULL DEFAULT '未チェック',
                last_check_result TEXT NOT NULL DEFAULT '未チェック',
                last_checked_at TEXT,
                monitor_enabled INTEGER NOT NULL DEFAULT 1,
                monitor_started_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS check_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER,
                checked_at TEXT NOT NULL,
                product_name TEXT NOT NULL,
                source_url TEXT NOT NULL,
                previous_price REAL,
                current_price REAL,
                stock_state TEXT NOT NULL,
                check_result TEXT NOT NULL,
                memo TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(item_id) REFERENCES monitor_items(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )
        existing_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(monitor_items)")
        }
        required_columns = {
            "monitor_enabled": "INTEGER NOT NULL DEFAULT 1",
            "monitor_started_at": "TEXT",
        }
        for column, definition in required_columns.items():
            if column not in existing_columns:
                connection.execute(f"ALTER TABLE monitor_items ADD COLUMN {column} {definition}")


def to_float(value: object, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return default


def fetch_items() -> list[dict[str, object]]:
    init_db()
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM monitor_items
            ORDER BY updated_at DESC, id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def fetch_history() -> list[dict[str, object]]:
    init_db()
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM check_history
            ORDER BY checked_at DESC, id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_setting(key: str, default: str = "") -> str:
    init_db()
    with get_connection() as connection:
        row = connection.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            (key,),
        ).fetchone()
    if row is None:
        return default
    return str(row["value"] or default)


def save_setting(key: str, value: str) -> None:
    init_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, now),
        )


def get_bool_setting(key: str, default: bool = False) -> bool:
    value = get_setting(key, "1" if default else "0").strip().lower()
    return value in ("1", "true", "yes", "on")


def get_int_setting(key: str, default: int) -> int:
    try:
        return int(get_setting(key, str(default)))
    except ValueError:
        return default


def monitor_status_text(row: dict[str, object]) -> str:
    if int(row.get("monitor_enabled") or 0) != 1:
        return "停止中"
    if row.get("status") == STATUS_PAUSED:
        return "停止中"
    if get_bool_setting(AUTO_MONITOR_ENABLED_KEY):
        return "自動監視中"
    return "待機中"


def save_item(values: dict[str, object], item_id: int | None = None) -> tuple[bool, str | None]:
    product_name = str(values.get("product_name", "")).strip()
    source_url = str(values.get("source_url", "")).strip()
    if not product_name:
        return False, "商品名を入力してください。"
    if not source_url:
        return False, "仕入れ元URLを入力してください。"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "product_name": product_name,
        "source_site": str(values.get("source_site", SOURCE_SITES[0])),
        "source_url": source_url,
        "current_purchase_price": to_float(values.get("current_purchase_price")),
        "ebay_listing_price": to_float(values.get("ebay_listing_price")),
        "expected_shipping_yen": to_float(values.get("expected_shipping_yen")),
        "memo": str(values.get("memo", "")).strip(),
        "status": str(values.get("status", STATUS_MONITORING)),
    }
    init_db()
    with get_connection() as connection:
        if item_id is None:
            connection.execute(
                """
                INSERT INTO monitor_items (
                    product_name, source_site, source_url, current_purchase_price,
                    last_checked_price, ebay_listing_price, expected_shipping_yen,
                    memo, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["product_name"],
                    payload["source_site"],
                    payload["source_url"],
                    payload["current_purchase_price"],
                    payload["current_purchase_price"],
                    payload["ebay_listing_price"],
                    payload["expected_shipping_yen"],
                    payload["memo"],
                    payload["status"],
                    now,
                    now,
                ),
            )
        else:
            connection.execute(
                """
                UPDATE monitor_items
                SET product_name = ?,
                    source_site = ?,
                    source_url = ?,
                    current_purchase_price = ?,
                    ebay_listing_price = ?,
                    expected_shipping_yen = ?,
                    memo = ?,
                    status = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    payload["product_name"],
                    payload["source_site"],
                    payload["source_url"],
                    payload["current_purchase_price"],
                    payload["ebay_listing_price"],
                    payload["expected_shipping_yen"],
                    payload["memo"],
                    payload["status"],
                    now,
                    item_id,
                ),
            )
    return True, None


def delete_item(item_id: int) -> None:
    init_db()
    with get_connection() as connection:
        connection.execute("DELETE FROM check_history WHERE item_id = ?", (item_id,))
        connection.execute("DELETE FROM monitor_items WHERE id = ?", (item_id,))


def extract_price(text: str) -> float | None:
    for pattern in PRICE_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            price = to_float(match.group(1))
            if price > 0:
                return price
    return None


def fetch_page_status(url: str) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 stock-price-monitor/1.0",
            "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            status_code = getattr(response, "status", 200)
            body = response.read(300000).decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 410):
            return {
                "page_exists": False,
                "stock_state": CHECK_PAGE_MISSING,
                "detected_price": None,
                "message": f"HTTP {exc.code}",
            }
        return {
            "page_exists": None,
            "stock_state": STOCK_NEEDS_CHECK,
            "detected_price": None,
            "message": f"HTTP {exc.code}: 自動確認できませんでした。",
        }
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {
            "page_exists": None,
            "stock_state": STOCK_NEEDS_CHECK,
            "detected_price": None,
            "message": f"取得失敗: {exc}",
        }

    lower_body = body.lower()
    sold_out = any(keyword.lower() in lower_body for keyword in SOLD_OUT_KEYWORDS)
    detected_price = extract_price(body)
    return {
        "page_exists": 200 <= int(status_code) < 400,
        "stock_state": STOCK_SOLD_OUT if sold_out else STOCK_AVAILABLE,
        "detected_price": detected_price,
        "message": "簡易チェック完了",
    }


def judge_check(
    row: dict[str, object],
    detected_price: float | None,
    stock_state: str,
    manual_price: float | None = None,
) -> dict[str, object]:
    previous_price = to_float(row.get("current_purchase_price"))
    current_price = manual_price if manual_price is not None and manual_price > 0 else detected_price
    previous_stock_state = str(row.get("last_stock_state") or "")
    result = RESULT_NEEDS_CHECK
    new_status = row.get("status", STATUS_MONITORING)

    if stock_state in (STOCK_SOLD_OUT, CHECK_PAGE_MISSING):
        result = RESULT_SOLD_OUT
        new_status = STATUS_SOLD_OUT
    elif previous_stock_state in (STOCK_SOLD_OUT, CHECK_PAGE_MISSING) and stock_state == STOCK_AVAILABLE:
        result = RESULT_RELISTED
        new_status = STATUS_MONITORING
    elif current_price is None:
        result = RESULT_NEEDS_CHECK
    elif current_price > previous_price:
        result = RESULT_PRICE_UP
        new_status = STATUS_PRICE_CHANGED
    elif current_price < previous_price:
        result = RESULT_PRICE_DOWN
        new_status = STATUS_PRICE_CHANGED
    else:
        result = RESULT_PRICE_SAME
        new_status = STATUS_MONITORING

    return {
        "previous_price": previous_price,
        "current_price": current_price,
        "stock_state": stock_state,
        "check_result": result,
        "new_status": new_status,
    }


def yen_text(value: object) -> str:
    if value in (None, ""):
        return "-"
    try:
        return f"{float(value):,.0f} 円"
    except (TypeError, ValueError):
        return "-"


def build_discord_message(
    row: dict[str, object],
    check: dict[str, object],
    checked_at: str,
) -> str:
    return "\n".join(
        [
            "無在庫販売 在庫・価格監視アラート",
            f"商品名: {row.get('product_name', '-')}",
            f"仕入れ元サイト: {row.get('source_site', '-')}",
            f"URL: {row.get('source_url', '-')}",
            f"前回価格: {yen_text(check.get('previous_price'))}",
            f"現在価格: {yen_text(check.get('current_price'))}",
            f"在庫状態: {check.get('stock_state', '-')}",
            f"検知内容: {check.get('check_result', '-')}",
            f"確認日時: {checked_at}",
        ]
    )


def send_discord_notification(
    row: dict[str, object],
    check: dict[str, object],
    checked_at: str,
) -> tuple[bool, str]:
    webhook_url = get_setting(DISCORD_WEBHOOK_SETTING_KEY).strip()
    if not webhook_url:
        return False, "Discord Webhook URLが未設定のため、画面上の通知のみ表示します。"

    payload = {
        "content": build_discord_message(row, check, checked_at),
        "allowed_mentions": {"parse": []},
    }
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "stock-price-monitor/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status_code = getattr(response, "status", 204)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return False, f"Discord通知に失敗しました: {exc}"

    if 200 <= int(status_code) < 300:
        return True, "Discordへ通知しました。"
    return False, f"Discord通知に失敗しました: HTTP {status_code}"


def send_discord_test_notification() -> tuple[bool, str]:
    webhook_url = get_setting(DISCORD_WEBHOOK_SETTING_KEY).strip()
    if not webhook_url:
        return False, "Discord Webhook URLが登録されていません。"

    sent_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "content": "\n".join(
            [
                "✅ Discord通知テスト",
                "",
                "Discord通知は正常に動作しています。",
                "",
                f"送信日時：{sent_at}",
                "アプリ名：無在庫価格監視ツール",
            ]
        ),
        "allowed_mentions": {"parse": []},
    }
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "stock-price-monitor/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status_code = getattr(response, "status", 204)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return False, f"Discordテスト通知に失敗しました: {exc}"

    if 200 <= int(status_code) < 300:
        return True, "Discordへテスト通知を送信しました。"
    return False, f"Discordテスト通知に失敗しました: HTTP {status_code}"


def record_check(
    row: dict[str, object],
    check: dict[str, object],
    memo: str,
) -> tuple[bool, str] | None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    current_price = check.get("current_price")
    updated_price = current_price if current_price is not None else to_float(row.get("current_purchase_price"))
    init_db()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO check_history (
                item_id, checked_at, product_name, source_url, previous_price,
                current_price, stock_state, check_result, memo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                now,
                row["product_name"],
                row["source_url"],
                check.get("previous_price"),
                current_price,
                check.get("stock_state"),
                check.get("check_result"),
                memo,
            ),
        )
        connection.execute(
            """
            UPDATE monitor_items
            SET current_purchase_price = ?,
                last_checked_price = ?,
                last_stock_state = ?,
                last_check_result = ?,
                status = ?,
                last_checked_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                updated_price,
                current_price,
                check.get("stock_state"),
                check.get("check_result"),
                check.get("new_status"),
                now,
                now,
                row["id"],
            ),
        )
    if check.get("check_result") in ALERT_RESULTS:
        return send_discord_notification(row, check, now)
    return None


def run_manual_check(
    row: dict[str, object],
    manual_price: float | None,
    manual_stock_state: str,
    memo: str,
) -> tuple[dict[str, object], tuple[bool, str] | None]:
    if manual_stock_state == "自動判定":
        page = fetch_page_status(str(row["source_url"]))
        stock_state = str(page["stock_state"])
        detected_price = page["detected_price"]
        note = f"{page['message']} / {memo}".strip(" /")
    else:
        stock_state = manual_stock_state
        detected_price = None
        note = memo or "手動チェック"
    check = judge_check(row, detected_price, stock_state, manual_price=manual_price)
    notification = record_check(row, check, note)
    return check, notification


def check_single_item_automatically(row: dict[str, object]) -> tuple[dict[str, object], tuple[bool, str] | None]:
    page = fetch_page_status(str(row["source_url"]))
    stock_state = str(page["stock_state"])
    detected_price = page["detected_price"]
    check = judge_check(row, detected_price, stock_state)
    note = str(page["message"])
    notification = record_check(row, check, note)
    return check, notification


def perform_auto_monitor_cycle() -> dict[str, int]:
    rows = fetch_items()
    checked = 0
    alerted = 0
    skipped = 0
    for row in rows:
        if int(row.get("monitor_enabled") or 0) != 1:
            skipped += 1
            continue
        if row.get("status") == STATUS_PAUSED:
            skipped += 1
            continue
        try:
            check, _notification = check_single_item_automatically(row)
            checked += 1
            if check.get("check_result") in ALERT_RESULTS:
                alerted += 1
        except Exception:
            skipped += 1
    return {"checked": checked, "alerted": alerted, "skipped": skipped}


def should_run_auto_monitor(now_ts: float) -> bool:
    if not get_bool_setting(AUTO_MONITOR_ENABLED_KEY):
        return False
    interval_minutes = get_int_setting(AUTO_MONITOR_INTERVAL_KEY, 5)
    interval_seconds = max(interval_minutes, 1) * 60
    last_run_raw = get_setting(AUTO_MONITOR_LAST_RUN_AT_KEY)
    if not last_run_raw:
        return True
    try:
        last_run = datetime.strptime(last_run_raw, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return True
    return now_ts - last_run.timestamp() >= interval_seconds


def auto_monitor_loop() -> None:
    while True:
        try:
            now_ts = time.time()
            if should_run_auto_monitor(now_ts):
                perform_auto_monitor_cycle()
                save_setting(
                    AUTO_MONITOR_LAST_RUN_AT_KEY,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
        except Exception:
            pass
        time.sleep(10)


@st.cache_resource
def start_background_monitor() -> threading.Thread:
    thread = threading.Thread(target=auto_monitor_loop, daemon=True)
    thread.start()
    return thread


def filtered_items(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    col1, col2, col3 = st.columns(3)
    search = col1.text_input("検索", placeholder="商品名・URL・メモ").strip().lower()
    source_filter = col2.selectbox("仕入れ元サイトで絞り込み", ("すべて", *SOURCE_SITES))
    status_filter = col3.selectbox("ステータスで絞り込み", ("すべて", *STATUS_OPTIONS))

    result = []
    for row in rows:
        text = " ".join(
            str(row.get(key, "") or "")
            for key in ("product_name", "source_url", "memo")
        ).lower()
        if search and search not in text:
            continue
        if source_filter != "すべて" and row.get("source_site") != source_filter:
            continue
        if status_filter != "すべて" and row.get("status") != status_filter:
            continue
        result.append(row)
    return result


def items_to_display(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "ID": row["id"],
            "商品名": row["product_name"],
            "仕入れ元": row["source_site"],
            "現在価格": row["current_purchase_price"],
            "eBay出品価格": row["ebay_listing_price"],
            "想定送料": row["expected_shipping_yen"],
            "ステータス": row["status"],
            "在庫状態": row.get("last_stock_state", ""),
            "判定結果": row.get("last_check_result", ""),
            "最終チェック": row.get("last_checked_at", ""),
            "監視状態": monitor_status_text(row),
            "監視開始日時": row.get("monitor_started_at", ""),
            "URL": row["source_url"],
            "メモ": row["memo"],
        }
        for row in rows
    ]


def rows_to_csv(rows: list[dict[str, object]]) -> str:
    output = io.StringIO()
    display_rows = items_to_display(rows)
    fieldnames = list(display_rows[0].keys()) if display_rows else [
        "ID", "商品名", "仕入れ元", "現在価格", "eBay出品価格", "想定送料",
        "ステータス", "在庫状態", "判定結果", "最終チェック", "監視状態",
        "監視開始日時", "URL", "メモ",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(display_rows)
    return output.getvalue()


def history_to_display(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "チェック日時": row["checked_at"],
            "商品名": row["product_name"],
            "URL": row["source_url"],
            "前回価格": row["previous_price"],
            "現在価格": row["current_price"],
            "在庫状態": row["stock_state"],
            "判定結果": row["check_result"],
            "メモ": row["memo"],
        }
        for row in rows
    ]


def history_to_csv(rows: list[dict[str, object]]) -> str:
    output = io.StringIO()
    display_rows = history_to_display(rows)
    fieldnames = list(display_rows[0].keys()) if display_rows else [
        "チェック日時", "商品名", "URL", "前回価格", "現在価格", "在庫状態", "判定結果", "メモ",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(display_rows)
    return output.getvalue()


def render_dashboard(rows: list[dict[str, object]]) -> None:
    st.subheader("ダッシュボード")
    sold_out = [row for row in rows if row.get("status") == STATUS_SOLD_OUT or row.get("last_check_result") == RESULT_SOLD_OUT]
    relisted = [row for row in rows if row.get("last_check_result") == RESULT_RELISTED]
    price_up = [row for row in rows if row.get("last_check_result") == RESULT_PRICE_UP]
    price_down = [row for row in rows if row.get("last_check_result") == RESULT_PRICE_DOWN]
    needs_check = [row for row in rows if row.get("last_check_result") == RESULT_NEEDS_CHECK or row.get("last_stock_state") == STOCK_NEEDS_CHECK]
    monitoring = [row for row in rows if row.get("status") == STATUS_MONITORING]

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("売り切れ商品", len(sold_out))
    col2.metric("再出品", len(relisted))
    col3.metric("価格上昇商品", len(price_up))
    col4.metric("価格下落商品", len(price_down))
    col5.metric("確認が必要", len(needs_check))
    col6.metric("監視中の商品数", len(monitoring))

    alerts = sold_out + relisted + price_up + price_down + needs_check
    if alerts:
        st.warning("アラートがあります。一覧またはチェック履歴を確認してください。")
        st.dataframe(
            items_to_display(alerts[:20]),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.success("現在、大きなアラートはありません。")


def render_registration() -> None:
    st.subheader("監視商品登録")
    with st.form("monitor_registration"):
        col1, col2 = st.columns(2)
        product_name = col1.text_input("商品名")
        source_site = col2.selectbox("仕入れ元サイト", SOURCE_SITES)
        source_url = st.text_input("仕入れ元URL")
        col3, col4, col5 = st.columns(3)
        current_purchase_price = col3.number_input("現在の仕入れ価格", min_value=0.0, step=100.0, format="%.0f")
        ebay_listing_price = col4.number_input("eBay出品価格", min_value=0.0, step=1.0, format="%.2f")
        expected_shipping_yen = col5.number_input("想定送料", min_value=0.0, step=100.0, format="%.0f")
        status = st.selectbox("ステータス", STATUS_OPTIONS)
        memo = st.text_area("メモ")
        submitted = st.form_submit_button("登録")

    if submitted:
        saved, error = save_item(
            {
                "product_name": product_name,
                "source_site": source_site,
                "source_url": source_url,
                "current_purchase_price": current_purchase_price,
                "ebay_listing_price": ebay_listing_price,
                "expected_shipping_yen": expected_shipping_yen,
                "status": status,
                "memo": memo,
            }
        )
        if saved:
            st.success("監視商品を登録しました。")
            st.rerun()
        else:
            st.error(error)


def render_item_editor(row: dict[str, object]) -> None:
    with st.expander(f"編集: {row['product_name']}", expanded=False):
        with st.form(f"edit_item_{row['id']}"):
            col1, col2 = st.columns(2)
            product_name = col1.text_input("商品名", value=str(row["product_name"]), key=f"name_{row['id']}")
            source_site = col2.selectbox(
                "仕入れ元サイト",
                SOURCE_SITES,
                index=SOURCE_SITES.index(str(row["source_site"])) if row["source_site"] in SOURCE_SITES else 0,
                key=f"site_{row['id']}",
            )
            source_url = st.text_input("仕入れ元URL", value=str(row["source_url"]), key=f"url_{row['id']}")
            col3, col4, col5 = st.columns(3)
            current_purchase_price = col3.number_input(
                "現在の仕入れ価格",
                min_value=0.0,
                value=to_float(row["current_purchase_price"]),
                step=100.0,
                format="%.0f",
                key=f"price_{row['id']}",
            )
            ebay_listing_price = col4.number_input(
                "eBay出品価格",
                min_value=0.0,
                value=to_float(row["ebay_listing_price"]),
                step=1.0,
                format="%.2f",
                key=f"ebay_{row['id']}",
            )
            expected_shipping_yen = col5.number_input(
                "想定送料",
                min_value=0.0,
                value=to_float(row["expected_shipping_yen"]),
                step=100.0,
                format="%.0f",
                key=f"shipping_{row['id']}",
            )
            status = st.selectbox(
                "ステータス",
                STATUS_OPTIONS,
                index=STATUS_OPTIONS.index(str(row["status"])) if row["status"] in STATUS_OPTIONS else 0,
                key=f"status_{row['id']}",
            )
            memo = st.text_area("メモ", value=str(row["memo"]), key=f"memo_{row['id']}")
            save_col, delete_col = st.columns(2)
            update = save_col.form_submit_button("保存")
            delete = delete_col.form_submit_button("削除")

        if update:
            saved, error = save_item(
                {
                    "product_name": product_name,
                    "source_site": source_site,
                    "source_url": source_url,
                    "current_purchase_price": current_purchase_price,
                    "ebay_listing_price": ebay_listing_price,
                    "expected_shipping_yen": expected_shipping_yen,
                    "status": status,
                    "memo": memo,
                },
                item_id=int(row["id"]),
            )
            if saved:
                st.success("更新しました。")
                st.rerun()
            else:
                st.error(error)

        if delete:
            delete_item(int(row["id"]))
            st.success("削除しました。")
            st.rerun()


def render_manual_check(row: dict[str, object]) -> None:
    with st.expander(f"手動チェック: {row['product_name']}", expanded=False):
        st.caption("自動判定はURL存在確認と売り切れキーワード・簡易価格抽出のみです。取得できない場合は確認が必要として記録します。")
        col1, col2 = st.columns(2)
        manual_stock_state = col1.selectbox(
            "在庫状態",
            ("自動判定", STOCK_AVAILABLE, STOCK_SOLD_OUT, STOCK_NEEDS_CHECK),
            key=f"stock_state_{row['id']}",
        )
        manual_price = col2.number_input(
            "現在価格（取得できない場合は手入力）",
            min_value=0.0,
            value=0.0,
            step=100.0,
            format="%.0f",
            key=f"manual_price_{row['id']}",
        )
        memo = st.text_input("チェックメモ", key=f"check_memo_{row['id']}")
        if st.button("今すぐ確認", key=f"check_{row['id']}"):
            check, notification = run_manual_check(
                row,
                manual_price if manual_price > 0 else None,
                manual_stock_state,
                memo,
            )
            messages = [("success", "チェック結果を保存しました。")]
            if check.get("check_result") in ALERT_RESULTS:
                messages.append(("warning", f"アラート: {check.get('check_result')}"))
            if notification:
                sent, message = notification
                if sent:
                    messages.append(("success", message))
                else:
                    messages.append(("info", message))
            st.session_state["last_check_messages"] = messages
            st.rerun()


def render_items(rows: list[dict[str, object]]) -> None:
    st.subheader("監視商品一覧")
    filtered = filtered_items(rows)
    st.dataframe(
        items_to_display(filtered),
        hide_index=True,
        use_container_width=True,
        column_config={
            "現在価格": st.column_config.NumberColumn(format="%.0f 円"),
            "eBay出品価格": st.column_config.NumberColumn(format="$%.2f"),
            "想定送料": st.column_config.NumberColumn(format="%.0f 円"),
        },
    )
    st.download_button(
        "監視商品一覧をCSVでダウンロード",
        rows_to_csv(filtered).encode("utf-8-sig"),
        file_name="stock_monitor_items.csv",
        mime="text/csv",
        disabled=not filtered,
    )
    if not filtered:
        st.info("条件に合う監視商品がありません。")
        return

    st.write("編集・削除・手動チェック")
    for row in filtered:
        render_manual_check(row)
        render_item_editor(row)


def render_history() -> None:
    st.subheader("チェック履歴")
    rows = fetch_history()
    search = st.text_input("履歴検索", placeholder="商品名・URL・メモ").strip().lower()
    if search:
        rows = [
            row for row in rows
            if search in " ".join(str(row.get(key, "") or "") for key in ("product_name", "source_url", "memo")).lower()
        ]
    st.dataframe(
        history_to_display(rows),
        hide_index=True,
        use_container_width=True,
        column_config={
            "前回価格": st.column_config.NumberColumn(format="%.0f 円"),
            "現在価格": st.column_config.NumberColumn(format="%.0f 円"),
        },
    )
    st.download_button(
        "チェック履歴をCSVでダウンロード",
        history_to_csv(rows).encode("utf-8-sig"),
        file_name="stock_check_history.csv",
        mime="text/csv",
        disabled=not rows,
    )


def start_auto_monitor(interval_minutes: int) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_setting(AUTO_MONITOR_ENABLED_KEY, "1")
    save_setting(AUTO_MONITOR_INTERVAL_KEY, str(interval_minutes))
    save_setting(AUTO_MONITOR_STARTED_AT_KEY, now)
    save_setting(AUTO_MONITOR_LAST_RUN_AT_KEY, "")
    init_db()
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE monitor_items
            SET monitor_enabled = 1,
                monitor_started_at = ?,
                updated_at = ?
            WHERE status <> ?
            """,
            (now, now, STATUS_PAUSED),
        )


def stop_auto_monitor() -> None:
    save_setting(AUTO_MONITOR_ENABLED_KEY, "0")


def render_auto_monitor_settings() -> None:
    st.write("自動監視設定")
    enabled = get_bool_setting(AUTO_MONITOR_ENABLED_KEY)
    interval_minutes = get_int_setting(AUTO_MONITOR_INTERVAL_KEY, 5)
    started_at = get_setting(AUTO_MONITOR_STARTED_AT_KEY, "-")
    last_run_at = get_setting(AUTO_MONITOR_LAST_RUN_AT_KEY, "-")

    col1, col2, col3 = st.columns(3)
    col1.metric("自動監視状態", "稼働中" if enabled else "停止中")
    col2.metric("監視間隔", f"{interval_minutes} 分")
    col3.metric("最終確認", last_run_at or "-")
    st.caption(f"監視開始日時: {started_at or '-'}")

    selected_interval = st.selectbox(
        "監視間隔",
        MONITOR_INTERVAL_OPTIONS,
        index=MONITOR_INTERVAL_OPTIONS.index(interval_minutes)
        if interval_minutes in MONITOR_INTERVAL_OPTIONS
        else 1,
        format_func=lambda value: f"{value}分",
        key="auto_monitor_interval_select",
    )
    start_col, stop_col, run_col = st.columns(3)
    if start_col.button("監視開始", type="primary"):
        start_auto_monitor(int(selected_interval))
        st.session_state["last_check_messages"] = [("success", "自動監視を開始しました。")]
        st.rerun()
    if stop_col.button("監視停止"):
        stop_auto_monitor()
        st.session_state["last_check_messages"] = [("info", "自動監視を停止しました。")]
        st.rerun()
    if run_col.button("全商品を今すぐ確認"):
        result = perform_auto_monitor_cycle()
        save_setting(AUTO_MONITOR_LAST_RUN_AT_KEY, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        st.session_state["last_check_messages"] = [
            (
                "success",
                f"確認完了: {result['checked']}件 / アラート {result['alerted']}件 / スキップ {result['skipped']}件",
            )
        ]
        st.rerun()


def render_settings() -> None:
    st.subheader("設定")
    render_auto_monitor_settings()
    st.divider()
    st.write("通知設定")
    current_webhook_url = get_setting(DISCORD_WEBHOOK_SETTING_KEY)
    with st.form("discord_webhook_settings"):
        webhook_url = st.text_input(
            "Discord Webhook URL",
            value=current_webhook_url,
            type="password",
            placeholder="https://discord.com/api/webhooks/...",
        )
        saved = st.form_submit_button("Webhook URLを保存")
    if saved:
        current_webhook_url = webhook_url.strip()
        save_setting(DISCORD_WEBHOOK_SETTING_KEY, current_webhook_url)
        if current_webhook_url:
            st.success("Discord Webhook URLを保存しました。")
        else:
            st.info("Discord Webhook URLを空にしました。未設定時は画面上の通知のみ表示します。")

    if current_webhook_url:
        st.success("Discord通知: 有効")
    else:
        st.info("Discord Webhook URLが未設定です。未設定時はアプリ画面上の通知のみ表示します。")

    if st.button("テスト通知を送信"):
        sent, message = send_discord_test_notification()
        if sent:
            st.success(message)
        else:
            st.error(message)

    st.divider()
    st.write("通知対象")
    st.write("- 売り切れ")
    st.write("- 価格上昇")
    st.write("- 価格下落")
    st.write("通知内容: 商品名、仕入れ元サイト、URL、前回価格、現在価格、在庫状態、検知内容、確認日時")

    st.divider()
    st.write("将来の通知連携を追加しやすいよう、チェック結果はSQLiteの履歴テーブルに保存しています。")
    st.write("- メール通知")
    st.write("- LINE通知")
    st.write("- Discord通知")
    st.divider()
    st.write("既存ツール連携の想定")
    st.write("売り切れ・価格変更を `stock_monitor.sqlite3` に保存しているため、将来的に出品管理ツール側からこのDBを参照できます。")
    st.code(str(DB_PATH), language="text")


def main() -> None:
    st.set_page_config(
        page_title="無在庫販売 在庫・価格監視ツール",
        page_icon="🔎",
        layout="wide",
    )
    init_db()
    start_background_monitor()
    st.title("無在庫販売 在庫・価格監視ツール")
    st.caption("仕入れ元URLを登録し、売り切れ・価格変更・確認が必要な商品を管理します。")
    for level, message in st.session_state.pop("last_check_messages", []):
        if level == "success":
            st.success(message)
        elif level == "warning":
            st.warning(message)
        elif level == "error":
            st.error(message)
        else:
            st.info(message)

    rows = fetch_items()
    tabs = st.tabs(("ダッシュボード", "監視商品登録", "監視商品一覧", "チェック履歴", "設定"))
    with tabs[0]:
        render_dashboard(rows)
    with tabs[1]:
        render_registration()
    with tabs[2]:
        render_items(rows)
    with tabs[3]:
        render_history()
    with tabs[4]:
        render_settings()

    st.caption(f"保存先SQLite: {DB_PATH}")


if __name__ == "__main__":
    main()
