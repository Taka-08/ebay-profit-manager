from __future__ import annotations

import csv
import html
import io
import json
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st

from app_database import database_location_label, get_database_connection
from app_paths import (
    resolve_exchange_rate_path,
    resolve_listing_db_path,
    resolve_listing_manager_dir,
    resolve_registration_event_path,
    resolve_registration_log_path,
)
from currency_config import (
    DEFAULT_CURRENCY,
    DEFAULT_JPY_RATES,
    SUPPORTED_CURRENCIES,
    YAHOO_FINANCE_SYMBOLS,
    currency_amount,
    currency_name,
    currency_option_label,
    currency_symbol,
    normalize_currency,
)
from platform_config import (
    FEE_MODE_AMOUNT,
    FEE_MODE_RATE,
    PLATFORM_EBAY,
    PLATFORM_IPHONE_RESALE,
    PLATFORM_MERCARI,
    PLATFORM_OPTIONS,
    SimpleProfitCalculation,
    calculate_simple_profit,
)


PRIMARY_EXCHANGE_RATE_API_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
PRIMARY_EXCHANGE_RATE_API_NAME = "Yahoo Finance market data"
FALLBACK_EXCHANGE_RATE_API_URL = "https://open.er-api.com/v6/latest/{currency}"
FALLBACK_EXCHANGE_RATE_API_NAME = "ExchangeRate-API open.er-api.com"
EXCHANGE_RATE_MAX_CHANGE_PERCENT = 5.0
EXCHANGE_RATE_MAX_AGE_HOURS = 96.0
LISTING_MANAGER_DIR = resolve_listing_manager_dir(__file__)
LISTING_DB_PATH = resolve_listing_db_path(__file__)
SHARED_EXCHANGE_RATE_PATH = resolve_exchange_rate_path(__file__)
REGISTRATION_EVENT_PATH = resolve_registration_event_path(__file__)
REGISTRATION_LOG_PATH = resolve_registration_log_path(__file__)
SHIPPING_RATE_PATH = Path(__file__).with_name("shipping_rates.json")
ZONOS_CONFIG_PATH = Path(__file__).with_name("zonos_prepay_config.json")

JAPAN_POST_CARRIER = "\u65e5\u672c\u90f5\u4fbf"
UNITED_STATES_COUNTRY = "\u30a2\u30e1\u30ea\u30ab"
DEFAULT_SALE_PRICE_FOREIGN = 0.0
DEFAULT_EBAY_FEE_RATE = 17.50
DEFAULT_AD_RATE = 0.0
DEFAULT_OVERSEAS_FEE_RATE = 2.00
DEFAULT_FIXED_FEE_USD = 0.30
DEFAULT_COPY_COST_YEN = 20.0
REGISTRATION_DEDUP_WINDOW_SECONDS = 30.0
HIDDEN_SHIPPING_SERVICES = frozenset(
    {
        (JAPAN_POST_CARRIER, "\u5c0f\u5f62\u5305\u88c5\u7269"),
    }
)

STATUS_ACTIVE = "出品中"
DEFAULT_COUNTRIES = ("アメリカ", "カナダ", "イギリス", "オーストラリア", "ドイツ", "フランス")


@dataclass(frozen=True)
class ProductInputs:
    product_name: str
    sku: str
    sale_price_usd: float
    buyer_shipping_usd: float
    purchase_price_yen: float
    domestic_shipping_yen: float
    packaging_yen: float
    destination_country: str
    weight_g: float
    length_cm: float
    width_cm: float
    height_cm: float
    ebay_fee_rate: float
    overseas_fee_rate: float
    ad_rate: float
    other_fee_yen: float
    fixed_fee_usd: float
    target_profit_yen: float
    product_url: str
    source_url: str
    exchange_rate: float
    postal_code: str = ""
    memo: str = ""
    currency_code: str = DEFAULT_CURRENCY
    usd_jpy_rate: float = DEFAULT_JPY_RATES["USD"]


@dataclass(frozen=True)
class SimpleProfitInputs:
    platform: str
    product_name: str
    iphone_model: str
    iphone_capacity: str
    sale_price_yen: float
    purchase_price_yen: float
    fee_input_mode: str
    fee_rate_percent: float
    fee_amount_yen: float
    shipping_yen: float
    repair_cost_yen: float
    parts_cost_yen: float
    other_cost_yen: float
    memo: str


@dataclass(frozen=True)
class ShippingResult:
    result_id: str
    carrier: str
    service: str
    actual_weight_g: float | None
    volumetric_weight_g: float | None
    applied_weight_g: float | None
    billing_weight_g: float | None
    base_shipping_yen: float | None
    fuel_surcharge_yen: float | None
    surcharge_yen: float | None
    additional_fee_yen: float | None
    other_additional_fee_yen: float | None
    total_shipping_yen: float | None
    profit_yen: float | None
    profit_margin: float | None
    shippable: bool
    status: str
    reason: str
    calculation_mode: str
    note: str
    zone: str = ""
    source_pdf: str = ""
    source_pages: tuple[int, ...] = ()
    rate_table_weight_g: float | None = None
    effective_from: str = ""
    effective_to: str = ""
    zonos_applied: bool = False
    zonos_base_shipping_yen: float | None = None
    zonos_fee_base_yen: float | None = None
    zonos_fee_rate_percent: float | None = None
    zonos_fee_yen: float | None = None
    zonos_duty_rate_percent: float | None = None
    zonos_duty_base_yen: float | None = None
    zonos_duty_yen: float | None = None
    zonos_total_shipping_yen: float | None = None
    zonos_config_effective_from: str = ""
    zonos_config_effective_to: str = ""
    zonos_calculated_at: str = ""
    zonos_note: str = ""
    is_recommended: bool = False
    is_cheapest: bool = False


@dataclass(frozen=True)
class RegistrationOutcome:
    success: bool
    error: str | None
    notification_error: str | None
    listing_id: int | None
    total_count: int
    database_path: str
    product_name: str


def yen(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f} 円"


def percent(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}%"


def compact_yen(value: float | int | None) -> str:
    if value is None:
        return "-"
    sign = "-" if value < 0 else ""
    return f"{sign}¥{abs(value):,.0f}"


def grams(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f}g"


def read_exchange_rate_store() -> dict[str, Any] | None:
    try:
        return json.loads(SHARED_EXCHANGE_RATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def read_shared_exchange_rate_data(
    currency_code: str = DEFAULT_CURRENCY,
) -> dict[str, Any] | None:
    currency = normalize_currency(currency_code)
    store = read_exchange_rate_store()
    if not store:
        return None
    rates = store.get("rates")
    if isinstance(rates, dict) and isinstance(rates.get(currency), dict):
        return dict(rates[currency])
    if currency == "USD" and isinstance(store.get("usd_jpy"), (int, float)):
        return store
    return None


def read_shared_exchange_rate(
    currency_code: str = DEFAULT_CURRENCY,
) -> float | None:
    currency = normalize_currency(currency_code)
    data = read_shared_exchange_rate_data(currency)
    if not data:
        return None
    rate = data.get("rate", data.get("usd_jpy"))
    if not isinstance(rate, (int, float)) or rate <= 0:
        return None
    return float(rate)


def save_shared_exchange_rate(
    rate: float,
    *,
    currency_code: str = DEFAULT_CURRENCY,
    source: str,
    raw_jpy: float | None = None,
    api_updated_at: str | None = None,
    fetched_at: str | None = None,
    mode: str = "api",
    api_rate: float | None = None,
    fallback_used: bool = False,
) -> None:
    """Save the shared rate while preserving API and manual-rate metadata."""
    currency = normalize_currency(currency_code)
    LISTING_MANAGER_DIR.mkdir(exist_ok=True)
    acquired_at = fetched_at or datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    record = {
        "currency_code": currency,
        "rate": float(rate),
        "source": source,
        "updated_at": acquired_at,
        "fetched_at": acquired_at,
        "api_updated_at": api_updated_at,
        "time_last_update_utc": api_updated_at,
        "raw_jpy": raw_jpy if raw_jpy is not None else float(rate),
        "mode": mode,
        "api_rate": api_rate if api_rate is not None else raw_jpy,
        "fallback_used": fallback_used,
        "pair": f"{currency}/JPY",
    }
    data = read_exchange_rate_store() or {}
    rates = dict(data.get("rates") or {})
    rates[currency] = record
    data["schema_version"] = 2
    data["rates"] = rates
    if currency == "USD":
        data.update(record)
        data["usd_jpy"] = float(rate)
    SHARED_EXCHANGE_RATE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def exchange_rate_request_json(url: str) -> dict[str, Any]:
    separator = "&" if "?" in url else "?"
    request = urllib.request.Request(
        f"{url}{separator}_={time.time_ns()}",
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache, no-store",
            "Pragma": "no-cache",
            "User-Agent": "Mozilla/5.0 EB-Research-Plus/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("為替APIの応答形式が不正です。")
    return payload


def format_api_timestamp(timestamp: int | float | None) -> str | None:
    if not isinstance(timestamp, (int, float)) or timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone().strftime(
        "%Y-%m-%d %H:%M:%S %z"
    )


def fetch_primary_exchange_rate(currency_code: str) -> dict[str, Any]:
    currency = normalize_currency(currency_code)
    symbol = YAHOO_FINANCE_SYMBOLS[currency]
    payload = exchange_rate_request_json(
        PRIMARY_EXCHANGE_RATE_API_URL.format(symbol=symbol)
    )
    chart = payload.get("chart") or {}
    results = chart.get("result") or []
    if not results:
        raise ValueError(
            f"メインAPIに{currency}/JPYデータがありません: "
            f"{chart.get('error') or '詳細不明'}"
        )
    meta = results[0].get("meta") or {}
    if meta.get("symbol") != symbol or meta.get("currency") != "JPY":
        raise ValueError(
            f"メインAPIから{currency}/JPY以外の通貨ペアが返されました。"
        )
    rate = meta.get("regularMarketPrice")
    if not isinstance(rate, (int, float)) or rate <= 0:
        raise ValueError(f"メインAPIに有効な{currency}/JPYレートがありません。")
    return {
        "currency_code": currency,
        "rate": float(rate),
        "raw_jpy": float(rate),
        "source": PRIMARY_EXCHANGE_RATE_API_NAME,
        "api_updated_at": format_api_timestamp(meta.get("regularMarketTime")),
        "fallback_used": False,
    }


def fetch_fallback_exchange_rate(currency_code: str) -> dict[str, Any]:
    currency = normalize_currency(currency_code)
    payload = exchange_rate_request_json(
        FALLBACK_EXCHANGE_RATE_API_URL.format(currency=currency)
    )
    if payload.get("base_code") != currency:
        raise ValueError(
            f"予備APIから{currency}基準以外の通貨データが返されました。"
        )
    rates = payload.get("rates") or {}
    rate = rates.get("JPY")
    if not isinstance(rate, (int, float)) or rate <= 0:
        raise ValueError("予備APIに有効なJPYレートがありません。")
    return {
        "currency_code": currency,
        "rate": float(rate),
        "raw_jpy": float(rate),
        "source": FALLBACK_EXCHANGE_RATE_API_NAME,
        "api_updated_at": payload.get("time_last_update_utc")
        or format_api_timestamp(payload.get("time_last_update_unix")),
        "fallback_used": True,
    }


def parse_saved_timestamp(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime

            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed.astimezone()


def validate_exchange_rate_result(
    result: dict[str, Any],
    previous_rate: float | None,
) -> None:
    rate = result.get("rate")
    if not isinstance(rate, (int, float)) or not math.isfinite(rate) or rate <= 0:
        raise ValueError("取得した為替レートが0以下、または数値ではありません。")
    if previous_rate and previous_rate > 0:
        change_percent = abs(float(rate) - previous_rate) / previous_rate * 100
        if change_percent > EXCHANGE_RATE_MAX_CHANGE_PERCENT:
            raise ValueError(
                f"前回値から{change_percent:.2f}%変動しているため自動適用を停止しました。"
            )
    api_updated = parse_saved_timestamp(result.get("api_updated_at"))
    if api_updated:
        age_hours = (
            datetime.now().astimezone() - api_updated
        ).total_seconds() / 3600
        if age_hours > EXCHANGE_RATE_MAX_AGE_HOURS:
            raise ValueError(
                f"APIの為替データが{age_hours:.0f}時間前のため自動適用を停止しました。"
            )


def fetch_exchange_rate(
    currency_code: str,
) -> tuple[dict[str, Any], str | None]:
    currency = normalize_currency(currency_code)
    primary_error: str | None = None
    try:
        return fetch_primary_exchange_rate(currency), None
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError, OSError) as exc:
        primary_error = str(exc)
    try:
        return fetch_fallback_exchange_rate(currency), primary_error
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(
            f"メインAPI: {primary_error or '取得失敗'} / 予備API: {exc}"
        ) from exc


def fetch_primary_usd_jpy_rate() -> dict[str, Any]:
    return fetch_primary_exchange_rate("USD")


def fetch_fallback_usd_jpy_rate() -> dict[str, Any]:
    return fetch_fallback_exchange_rate("USD")


def fetch_usd_jpy_rate() -> tuple[dict[str, Any], str | None]:
    return fetch_exchange_rate("USD")


def update_exchange_rate_from_api(
    *,
    trigger: str = "button",
    currency_code: str | None = None,
) -> None:
    currency = normalize_currency(
        currency_code or st.session_state.get("exchange_currency")
    )
    previous_data = read_shared_exchange_rate_data(currency) or {}
    before = read_shared_exchange_rate(currency)
    try:
        result, primary_error = fetch_exchange_rate(currency)
        validate_exchange_rate_result(result, before)
        rate = float(result["rate"])
        fetched_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
        save_shared_exchange_rate(
            rate,
            currency_code=currency,
            source=str(result["source"]),
            raw_jpy=float(result["raw_jpy"]),
            api_updated_at=result.get("api_updated_at"),
            fetched_at=fetched_at,
            mode="api",
            api_rate=rate,
            fallback_used=bool(result.get("fallback_used")),
        )
        st.session_state.exchange_rate = rate
        st.session_state.exchange_rate_input = rate
        st.session_state.exchange_rate_manual = False
        st.session_state.exchange_rate_message = {
            "type": "success",
            "before": before,
            "after": rate,
            "api_updated_before": previous_data.get("api_updated_at")
            or previous_data.get("time_last_update_utc"),
            "api_updated_after": result.get("api_updated_at"),
            "source": result["source"],
            "fallback_used": bool(result.get("fallback_used")),
            "primary_error": primary_error,
            "trigger": trigger,
            "currency_code": currency,
        }
    except (
        urllib.error.URLError,
        TimeoutError,
        ValueError,
        json.JSONDecodeError,
        OSError,
        RuntimeError,
    ) as exc:
        fallback = before or float(
            st.session_state.get("exchange_rate", DEFAULT_JPY_RATES[currency])
        )
        st.session_state.exchange_rate = fallback
        st.session_state.exchange_rate_input = fallback
        st.session_state.exchange_rate_message = {
            "type": "error",
            "before": before,
            "after": fallback,
            "error": str(exc),
            "trigger": trigger,
            "currency_code": currency,
        }


def load_exchange_rate(currency_code: str = DEFAULT_CURRENCY) -> None:
    currency = normalize_currency(currency_code)
    if st.session_state.get("exchange_rate_loaded_currency") != currency:
        saved_data = read_shared_exchange_rate_data(currency) or {}
        saved = read_shared_exchange_rate(currency)
        st.session_state.exchange_rate = (
            saved if saved else DEFAULT_JPY_RATES[currency]
        )
        st.session_state.exchange_rate_input = st.session_state.exchange_rate
        st.session_state.exchange_rate_manual = saved_data.get("mode") == "manual"
        st.session_state.exchange_rate_loaded_currency = currency
    startup_key = f"exchange_rate_startup_checked_{currency}"
    if not st.session_state.get(startup_key):
        st.session_state[startup_key] = True
        update_exchange_rate_from_api(trigger="startup", currency_code=currency)


def apply_manual_exchange_rate(currency_code: str | None = None) -> None:
    currency = normalize_currency(
        currency_code or st.session_state.get("exchange_currency")
    )
    rate = float(st.session_state.get("exchange_rate_input", 0))
    if rate <= 0:
        return
    previous = read_shared_exchange_rate_data(currency) or {}
    st.session_state.exchange_rate = rate
    st.session_state.exchange_rate_manual = True
    save_shared_exchange_rate(
        rate,
        currency_code=currency,
        source="手動入力",
        raw_jpy=previous.get("raw_jpy"),
        api_updated_at=previous.get("api_updated_at")
        or previous.get("time_last_update_utc"),
        mode="manual",
        api_rate=previous.get("api_rate") or previous.get("raw_jpy"),
        fallback_used=bool(previous.get("fallback_used")),
    )
    st.session_state.exchange_rate_message = {
        "type": "manual",
        "after": rate,
        "currency_code": currency,
    }


def default_zonos_config() -> dict[str, Any]:
    return {
        "enabled": True,
        "applicable_countries": [UNITED_STATES_COUNTRY],
        "applicable_carriers": [JAPAN_POST_CARRIER],
        "applicable_services": ["EMS", "\u56fd\u969b\u30a8\u30a2\u30d1\u30b1\u30c3\u30c8", "\u5c0f\u5f62\u5305\u88c5\u7269", "\u56fd\u969b\u5c0f\u5305"],
        "duty": {
            "rate_percent": 10.0,
            "base": "product_price_yen",
            "effective_from": "2026-07-12",
            "effective_to": "",
        },
        "fee": {
            "base": "product_price_yen_plus_shipping",
            "rounding": "half_up",
            "above_max": "use_last_rate",
            "effective_from": "2026-07-12",
            "effective_to": "",
            "points": [
                {"amountJpy": 2000, "ratePercent": 30.0},
                {"amountJpy": 2500, "ratePercent": 24.0},
                {"amountJpy": 3000, "ratePercent": 20.0},
                {"amountJpy": 4000, "ratePercent": 15.0},
                {"amountJpy": 5000, "ratePercent": 12.0},
                {"amountJpy": 6000, "ratePercent": 10.0},
                {"amountJpy": 7000, "ratePercent": 9.0},
                {"amountJpy": 8000, "ratePercent": 8.0},
                {"amountJpy": 10000, "ratePercent": 6.83},
                {"amountJpy": 15000, "ratePercent": 4.89},
                {"amountJpy": 20000, "ratePercent": 3.91},
            ],
        },
        "note": "US-bound Japan Post shipments use Zonos Prepay with Section 122 duty.",
    }


def ensure_zonos_config_file() -> None:
    if not ZONOS_CONFIG_PATH.exists():
        ZONOS_CONFIG_PATH.write_text(
            json.dumps(default_zonos_config(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def load_zonos_config() -> dict[str, Any]:
    ensure_zonos_config_file()
    try:
        data = json.loads(ZONOS_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_zonos_config()
    if not isinstance(data, dict):
        return default_zonos_config()
    return data


def save_zonos_config(config: dict[str, Any]) -> None:
    ZONOS_CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def round_yen(value: float, method: str = "half_up") -> float:
    if method != "half_up":
        return float(round(value))
    if value >= 0:
        return float(math.floor(value + 0.5))
    return float(math.ceil(value - 0.5))


def zonos_fee_rate_percent(base_amount_yen: float, points: list[dict[str, Any]]) -> float:
    clean_points = sorted(
        (
            (float(point["amountJpy"]), float(point["ratePercent"]))
            for point in points
            if isinstance(point, dict) and "amountJpy" in point and "ratePercent" in point
        ),
        key=lambda item: item[0],
    )
    if not clean_points:
        return 0.0
    if base_amount_yen <= clean_points[0][0]:
        return clean_points[0][1]
    for (prev_amount, prev_rate), (next_amount, next_rate) in zip(clean_points, clean_points[1:]):
        if base_amount_yen <= next_amount:
            ratio = (base_amount_yen - prev_amount) / (next_amount - prev_amount)
            return prev_rate + ratio * (next_rate - prev_rate)
    return clean_points[-1][1]


def zonos_base_amount(base_type: str, sale_price_yen: float, base_shipping_yen: float) -> float:
    if base_type == "product_price_yen_plus_shipping":
        return sale_price_yen + base_shipping_yen
    return sale_price_yen


def should_apply_zonos(service: dict[str, Any], inputs: ProductInputs, config: dict[str, Any]) -> bool:
    if not config.get("enabled", True):
        return False
    carrier = str(service.get("carrier", ""))
    service_name = str(service.get("service", ""))
    countries = config.get("applicable_countries") or []
    carriers = config.get("applicable_carriers") or []
    services = config.get("applicable_services") or []
    return (
        inputs.destination_country in countries
        and carrier in carriers
        and service_name in services
    )


def calculate_zonos_amounts(
    service: dict[str, Any],
    inputs: ProductInputs,
    base_shipping_total_yen: float,
) -> dict[str, Any] | None:
    config = load_zonos_config()
    if not should_apply_zonos(service, inputs, config):
        return None

    sale_price_yen = inputs.sale_price_usd * inputs.exchange_rate
    duty_config = config.get("duty") or {}
    fee_config = config.get("fee") or {}
    rounding = str(fee_config.get("rounding") or "half_up")

    duty_rate = float(duty_config.get("rate_percent", 10.0) or 0)
    duty_base = zonos_base_amount(str(duty_config.get("base") or "product_price_yen"), sale_price_yen, base_shipping_total_yen)
    duty_yen = round_yen(duty_base * duty_rate / 100, rounding)

    fee_base = zonos_base_amount(str(fee_config.get("base") or "product_price_yen_plus_shipping"), sale_price_yen, base_shipping_total_yen)
    fee_rate = zonos_fee_rate_percent(fee_base, list(fee_config.get("points") or []))
    fee_yen = round_yen(fee_base * fee_rate / 100, rounding)
    total = base_shipping_total_yen + duty_yen + fee_yen

    return {
        "applied": True,
        "base_shipping_yen": base_shipping_total_yen,
        "fee_base_yen": fee_base,
        "fee_rate_percent": fee_rate,
        "fee_yen": fee_yen,
        "duty_rate_percent": duty_rate,
        "duty_base_yen": duty_base,
        "duty_yen": duty_yen,
        "total_shipping_yen": total,
        "effective_from": str(duty_config.get("effective_from") or fee_config.get("effective_from") or ""),
        "effective_to": str(duty_config.get("effective_to") or fee_config.get("effective_to") or ""),
        "calculated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "note": str(config.get("note") or ""),
    }


def load_shipping_rate_book() -> dict[str, Any]:
    if not SHIPPING_RATE_PATH.exists():
        return {"services": []}
    try:
        data = json.loads(SHIPPING_RATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        st.error(f"送料データを読み込めません: {SHIPPING_RATE_PATH}")
        return {"services": []}
    if not isinstance(data, dict) or not isinstance(data.get("services"), list):
        st.error("送料データの形式が正しくありません。")
        return {"services": []}
    return data


def get_connection() -> Any:
    return get_database_connection(LISTING_DB_PATH)


def init_listing_db() -> None:
    with get_connection() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT NOT NULL,
                platform TEXT NOT NULL DEFAULT 'eBay',
                listing_date TEXT NOT NULL,
                listing_price_usd REAL NOT NULL DEFAULT 0,
                listing_price REAL NOT NULL DEFAULT 0,
                buyer_shipping_usd REAL NOT NULL DEFAULT 0,
                exchange_rate REAL NOT NULL DEFAULT 0,
                purchase_price_yen REAL NOT NULL DEFAULT 0,
                purchase_price REAL NOT NULL DEFAULT 0,
                domestic_shipping_yen REAL NOT NULL DEFAULT 0,
                international_shipping_yen REAL NOT NULL DEFAULT 0,
                packaging_yen REAL NOT NULL DEFAULT 0,
                other_cost_yen REAL NOT NULL DEFAULT 0,
                expected_shipping REAL NOT NULL DEFAULT 0,
                ebay_fee_yen REAL NOT NULL DEFAULT 0,
                ebay_fee_rate REAL NOT NULL DEFAULT 0,
                ad_fee_yen REAL NOT NULL DEFAULT 0,
                promoted_listing_rate REAL NOT NULL DEFAULT 0,
                exchange_spread_rate REAL NOT NULL DEFAULT 0,
                fixed_fee_usd REAL NOT NULL DEFAULT 0,
                target_profit_yen REAL NOT NULL DEFAULT 0,
                expected_profit_yen REAL NOT NULL DEFAULT 0,
                profit_yen REAL NOT NULL DEFAULT 0,
                profit_margin REAL NOT NULL DEFAULT 0,
                roi REAL,
                gross_sales_yen REAL NOT NULL DEFAULT 0,
                break_even_sale_price_usd REAL,
                target_sale_price_usd REAL,
                search_keyword TEXT NOT NULL DEFAULT '',
                monthly_sales REAL NOT NULL DEFAULT 0,
                competitor_count REAL NOT NULL DEFAULT 0,
                product_url TEXT NOT NULL DEFAULT '',
                research_shipping_weight_g REAL NOT NULL DEFAULT 0,
                inventory_risk TEXT NOT NULL DEFAULT '',
                research_memo TEXT NOT NULL DEFAULT '',
                calculated_at TEXT,
                status TEXT NOT NULL,
                actual_sale_price_usd REAL,
                actual_sale_price REAL,
                actual_buyer_shipping_usd REAL,
                actual_ebay_fee_usd REAL,
                actual_ad_fee_usd REAL,
                actual_fixed_fee_usd REAL,
                actual_fee_schema_version INTEGER NOT NULL DEFAULT 1,
                effective_ebay_fee_rate REAL,
                effective_ad_fee_rate REAL,
                actual_shipping_yen REAL,
                actual_shipping REAL,
                shipping_carrier TEXT,
                shipping_service TEXT,
                shipping_weight_g REAL,
                actual_profit_yen REAL,
                actual_profit REAL,
                actual_profit_margin REAL,
                sold_date TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        existing = {
            row[1] for row in connection.execute("PRAGMA table_info(listings)")
        }
        required_columns = {
            "currency_code": "TEXT NOT NULL DEFAULT 'USD'",
            "usd_jpy_rate": "REAL NOT NULL DEFAULT 0",
            "actual_usd_jpy_rate": "REAL",
            "actual_order_revenue_yen": "REAL",
            "actual_fee_schema_version": "INTEGER NOT NULL DEFAULT 1",
            "sku": "TEXT NOT NULL DEFAULT ''",
            "source_url": "TEXT NOT NULL DEFAULT ''",
            "destination_country": "TEXT NOT NULL DEFAULT ''",
            "destination_postal_code": "TEXT NOT NULL DEFAULT ''",
            "sale_price_yen": "REAL NOT NULL DEFAULT 0",
            "package_weight_g": "REAL NOT NULL DEFAULT 0",
            "package_length_cm": "REAL NOT NULL DEFAULT 0",
            "package_width_cm": "REAL NOT NULL DEFAULT 0",
            "package_height_cm": "REAL NOT NULL DEFAULT 0",
            "expected_shipping_carrier": "TEXT NOT NULL DEFAULT ''",
            "expected_shipping_service": "TEXT NOT NULL DEFAULT ''",
            "planned_shipping_yen": "REAL NOT NULL DEFAULT 0",
            "planned_profit_margin": "REAL NOT NULL DEFAULT 0",
            "planned_base_shipping_yen": "REAL NOT NULL DEFAULT 0",
            "planned_fuel_surcharge_yen": "REAL NOT NULL DEFAULT 0",
            "planned_additional_fee_yen": "REAL NOT NULL DEFAULT 0",
            "planned_shipping_status": "TEXT NOT NULL DEFAULT ''",
            "planned_shipping_reason": "TEXT NOT NULL DEFAULT ''",
            "rate_table_weight_g": "REAL",
            "shipping_breakdown_json": "TEXT NOT NULL DEFAULT ''",
            "shipping_carrier": "TEXT",
            "shipping_service": "TEXT",
            "shipping_weight_g": "REAL",
            "actual_profit_margin": "REAL",
            "overseas_fee_rate": "REAL NOT NULL DEFAULT 0",
            "overseas_fee_yen": "REAL NOT NULL DEFAULT 0",
            "other_fee_yen": "REAL NOT NULL DEFAULT 0",
            "shipping_calculation_mode": "TEXT NOT NULL DEFAULT ''",
            "volumetric_weight_g": "REAL",
            "applied_weight_g": "REAL",
            "billing_weight_g": "REAL",
            "zonos_applied": "INTEGER NOT NULL DEFAULT 0",
            "zonos_base_shipping_yen": "REAL NOT NULL DEFAULT 0",
            "zonos_fee_base_yen": "REAL NOT NULL DEFAULT 0",
            "zonos_fee_rate_percent": "REAL NOT NULL DEFAULT 0",
            "zonos_fee_yen": "REAL NOT NULL DEFAULT 0",
            "zonos_duty_rate_percent": "REAL NOT NULL DEFAULT 0",
            "zonos_duty_base_yen": "REAL NOT NULL DEFAULT 0",
            "zonos_duty_yen": "REAL NOT NULL DEFAULT 0",
            "zonos_total_shipping_yen": "REAL NOT NULL DEFAULT 0",
            "zonos_config_effective_from": "TEXT NOT NULL DEFAULT ''",
            "zonos_config_effective_to": "TEXT NOT NULL DEFAULT ''",
            "registered_at": "TEXT",
            "sales_fee_input_mode": "TEXT NOT NULL DEFAULT 'rate'",
            "sales_fee_rate": "REAL NOT NULL DEFAULT 0",
            "sales_fee_yen": "REAL NOT NULL DEFAULT 0",
            "simple_shipping_yen": "REAL NOT NULL DEFAULT 0",
            "repair_cost_yen": "REAL NOT NULL DEFAULT 0",
            "parts_cost_yen": "REAL NOT NULL DEFAULT 0",
            "iphone_model": "TEXT NOT NULL DEFAULT ''",
            "iphone_capacity": "TEXT NOT NULL DEFAULT ''",
            "platform_memo": "TEXT NOT NULL DEFAULT ''",
            "actual_sales_fee_yen": "REAL",
            "actual_repair_cost_yen": "REAL",
            "actual_parts_cost_yen": "REAL",
        }
        for column, definition in required_columns.items():
            if column not in existing:
                connection.execute(
                    f"ALTER TABLE listings ADD COLUMN {column} {definition}"
                )
        connection.execute(
            "UPDATE listings SET platform = ? WHERE platform = ?",
            (PLATFORM_IPHONE_RESALE, "その他"),
        )


def ceil_to_unit(value: float, unit: float) -> float:
    if unit <= 0:
        return value
    return math.ceil(value / unit) * unit


def digits_only(value: str) -> str:
    return "".join(char for char in str(value) if char.isdigit())


def resolve_service_zone(
    service: dict[str, Any],
    country: str,
    postal_code: str = "",
) -> tuple[str | None, str | None]:
    rules = service.get("country_zone_rules") or {}
    rule = rules.get(country)
    if rule is None:
        return None, "配送対象外の国です"
    if isinstance(rule, str):
        return rule, None
    if not isinstance(rule, dict):
        return None, "配送ゾーン設定が不正です"

    postal_digits = digits_only(postal_code)
    if rule.get("requires_postal_code") and not postal_digits:
        return None, "この国は郵便番号を入力するとゾーンを判定できます"

    for prefix_rule in rule.get("postal_prefix_zones", []):
        prefixes = {str(prefix) for prefix in prefix_rule.get("prefixes", [])}
        if postal_digits[:3] in prefixes:
            return str(prefix_rule.get("zone")), None

    for range_rule in rule.get("postal_range_zones", []):
        if len(postal_digits) < 5:
            continue
        prefix_value = int(postal_digits[:5])
        if int(range_rule.get("start", -1)) <= prefix_value <= int(range_rule.get("end", -1)):
            return str(range_rule.get("zone")), None

    default_zone = rule.get("default_zone")
    if default_zone:
        return str(default_zone), None
    return None, "配送ゾーンを判定できません"


def zone_value(
    service: dict[str, Any],
    key: str,
    zone: str | None,
    default: Any = None,
) -> Any:
    zone_values = service.get(f"{key}_by_zone") or {}
    if zone is not None and zone in zone_values:
        return zone_values[zone]
    return service.get(key, default)


def needs_dimensions(service: dict[str, Any]) -> bool:
    return bool(service.get("volumetric_divisor_cm3_per_kg") or service.get("max_size"))


def size_input_state(inputs: ProductInputs) -> str:
    entered = [inputs.length_cm > 0, inputs.width_cm > 0, inputs.height_cm > 0]
    if all(entered):
        return "complete"
    if any(entered):
        return "partial"
    return "none"


def size_complete(inputs: ProductInputs) -> bool:
    return size_input_state(inputs) == "complete"


def calculation_mode(inputs: ProductInputs) -> str:
    if size_complete(inputs):
        return "サイズ反映済み"
    return "概算"


def calculation_mode_label(inputs: ProductInputs) -> str:
    if size_complete(inputs):
        return "実重量＋容積重量を反映"
    return "実重量のみの概算"


def approximate_note(service: dict[str, Any], inputs: ProductInputs) -> str:
    state = size_input_state(inputs)
    if state == "complete":
        return ""
    if state == "partial":
        return "サイズを計算するには長さ・幅・高さをすべて入力してください。実重量のみで概算しています。"
    if service.get("volumetric_divisor_cm3_per_kg"):
        return "実重量のみで算出した概算料金です。梱包サイズを入力すると、より正確に計算できます。"
    return "実重量のみで算出した概算料金です。"


def calculate_volumetric_weight_g(
    service: dict[str, Any],
    inputs: ProductInputs,
) -> float | None:
    divisor = service.get("volumetric_divisor_cm3_per_kg")
    if not divisor:
        return None
    if not size_complete(inputs):
        return None
    volume_cm3 = inputs.length_cm * inputs.width_cm * inputs.height_cm
    return volume_cm3 / float(divisor) * 1000


def size_limit_reason(service: dict[str, Any], inputs: ProductInputs, zone: str | None = None) -> str | None:
    max_size = zone_value(service, "max_size", zone, {}) or {}
    if not max_size:
        return None
    if not size_complete(inputs):
        return None

    length = inputs.length_cm
    width = inputs.width_cm
    height = inputs.height_cm
    limits = (
        ("長さ", length, max_size.get("length_cm")),
        ("幅", width, max_size.get("width_cm")),
        ("高さ", height, max_size.get("height_cm")),
    )
    for label, current, maximum in limits:
        if maximum and current > float(maximum):
            return f"{label}が上限を超えています"

    length_plus_girth = length + 2 * (width + height)
    max_lpg = max_size.get("length_plus_girth_cm")
    if max_lpg and length_plus_girth > float(max_lpg):
        return "長さ＋胴回りが上限を超えています"
    max_sum = max_size.get("length_width_height_sum_cm")
    if max_sum and length + width + height > float(max_sum):
        return "長さ＋幅＋高さが上限を超えています"
    max_volume = max_size.get("volume_cm3")
    if max_volume and length * width * height > float(max_volume):
        return "容積が上限を超えています"
    max_volumetric_g = max_size.get("volumetric_weight_g")
    volumetric_weight_g = calculate_volumetric_weight_g(service, inputs)
    if max_volumetric_g and volumetric_weight_g and volumetric_weight_g > float(max_volumetric_g):
        return "容積重量が上限を超えています"
    return None


def find_rate_row(
    service: dict[str, Any],
    country: str,
    zone: str | None,
    billing_weight_g: float,
) -> dict[str, Any] | None:
    for row in service.get("rates", []):
        row_country = row.get("country")
        row_zone = row.get("zone")
        if row_zone is not None and zone is not None and row_zone != zone:
            continue
        if row_zone is not None and zone is None:
            continue
        if row_country and row_country not in (country, "ALL", "すべて"):
            continue
        if float(row.get("min_weight_g", 0)) <= billing_weight_g <= float(row.get("max_weight_g", 0)):
            return row
    return None


def calculate_one_shipping_result(
    service: dict[str, Any],
    inputs: ProductInputs,
) -> ShippingResult:
    carrier = str(service.get("carrier", ""))
    service_name = str(service.get("service", ""))
    result_id = f"{carrier}::{service_name}"
    mode = calculation_mode_label(inputs)
    note = approximate_note(service, inputs)
    service_note = str(service.get("note") or "").strip()
    if service_note:
        note = f"{note}\n{service_note}" if note else service_note

    if inputs.destination_country.strip() == "":
        return unavailable_result(result_id, carrier, service_name, inputs, "入力不足", "配送先の国が未入力です")
    if inputs.weight_g <= 0:
        return unavailable_result(result_id, carrier, service_name, inputs, "入力不足", "実重量が未入力です")

    countries = service.get("countries") or []
    if countries and inputs.destination_country not in countries:
        return unavailable_result(result_id, carrier, service_name, inputs, "発送不可", "配送対象外の国です")

    zone, zone_reason = resolve_service_zone(service, inputs.destination_country, inputs.postal_code)
    if zone_reason:
        return unavailable_result(result_id, carrier, service_name, inputs, "発送不可", zone_reason)

    size_reason = size_limit_reason(service, inputs, zone)
    if size_reason:
        return unavailable_result(result_id, carrier, service_name, inputs, "発送不可", size_reason)

    volumetric_weight_g = calculate_volumetric_weight_g(service, inputs)
    weight_basis = service.get("weight_basis", "actual")
    if weight_basis == "greater" and volumetric_weight_g is not None:
        applied_weight_g = max(inputs.weight_g, volumetric_weight_g)
    elif weight_basis == "volumetric" and volumetric_weight_g is not None:
        applied_weight_g = volumetric_weight_g
    else:
        applied_weight_g = inputs.weight_g

    rounding_unit_g = float(service.get("rounding_unit_g") or 1)
    billing_weight_g = ceil_to_unit(applied_weight_g, rounding_unit_g)
    max_actual_weight_g = zone_value(service, "max_actual_weight_g", zone)
    if max_actual_weight_g and inputs.weight_g > float(max_actual_weight_g):
        return unavailable_result(
            result_id,
            carrier,
            service_name,
            inputs,
            "発送不可",
            "実重量超過",
            volumetric_weight_g=volumetric_weight_g,
            applied_weight_g=applied_weight_g,
            billing_weight_g=billing_weight_g,
        )

    max_weight_g = zone_value(service, "max_weight_g", zone)
    if max_weight_g and billing_weight_g > float(max_weight_g):
        return unavailable_result(
            result_id,
            carrier,
            service_name,
            inputs,
            "発送不可",
            "重量超過",
            volumetric_weight_g=volumetric_weight_g,
            applied_weight_g=applied_weight_g,
            billing_weight_g=billing_weight_g,
        )

    rate = find_rate_row(service, inputs.destination_country, zone, billing_weight_g)
    if rate is None:
        return unavailable_result(
            result_id,
            carrier,
            service_name,
            inputs,
            "料金未登録",
            "該当する重量・国の料金データがありません",
            volumetric_weight_g=volumetric_weight_g,
            applied_weight_g=applied_weight_g,
            billing_weight_g=billing_weight_g,
            zone=zone or "",
            source_pdf=str(service.get("source_pdf") or ""),
            source_pages=tuple(int(page) for page in service.get("source_pages", []) if isinstance(page, int)),
            rate_table_weight_g=billing_weight_g,
            effective_from=str(service.get("effective_from") or ""),
            effective_to=str(service.get("effective_to") or ""),
        )

    base_shipping_yen = float(rate.get("base_shipping_yen", 0))
    fuel_rate = float(rate.get("fuel_surcharge_rate", service.get("fuel_surcharge_rate", 0)) or 0)
    fuel_surcharge_yen = base_shipping_yen * fuel_rate / 100
    surcharge_yen = float(rate.get("surcharge_yen", service.get("surcharge_yen", 0)) or 0)
    additional_fee_yen = float(rate.get("additional_fee_yen", service.get("additional_fee_yen", 0)) or 0)
    other_additional_fee_yen = float(rate.get("other_additional_fee_yen", service.get("other_additional_fee_yen", 0)) or 0)
    total_shipping_yen = (
        base_shipping_yen
        + fuel_surcharge_yen
        + surcharge_yen
        + additional_fee_yen
        + other_additional_fee_yen
    )
    sale_price_yen = inputs.sale_price_usd * inputs.exchange_rate
    gross_sales_yen = inputs.sale_price_usd * inputs.exchange_rate
    zonos_amounts = calculate_zonos_amounts(service, inputs, total_shipping_yen)
    if zonos_amounts:
        total_shipping_yen = float(zonos_amounts["total_shipping_yen"])
        note = f"{note}\nZonos Prepay included." if note else "Zonos Prepay included."
    ebay_fee_yen = gross_sales_yen * inputs.ebay_fee_rate / 100
    overseas_fee_yen = gross_sales_yen * inputs.overseas_fee_rate / 100
    ad_fee_yen = gross_sales_yen * inputs.ad_rate / 100
    fixed_fee_yen = inputs.fixed_fee_usd * inputs.usd_jpy_rate
    profit_yen = (
        gross_sales_yen
        - inputs.purchase_price_yen
        - inputs.domestic_shipping_yen
        - inputs.packaging_yen
        - ebay_fee_yen
        - overseas_fee_yen
        - ad_fee_yen
        - fixed_fee_yen
        - inputs.other_fee_yen
        - total_shipping_yen
    )
    profit_margin = profit_yen / gross_sales_yen * 100 if gross_sales_yen > 0 else None

    return ShippingResult(
        result_id=result_id,
        carrier=carrier,
        service=service_name,
        actual_weight_g=inputs.weight_g,
        volumetric_weight_g=volumetric_weight_g,
        applied_weight_g=applied_weight_g,
        billing_weight_g=billing_weight_g,
        base_shipping_yen=base_shipping_yen,
        fuel_surcharge_yen=fuel_surcharge_yen,
        surcharge_yen=surcharge_yen,
        additional_fee_yen=additional_fee_yen,
        other_additional_fee_yen=other_additional_fee_yen,
        total_shipping_yen=total_shipping_yen,
        profit_yen=profit_yen,
        profit_margin=profit_margin,
        shippable=True,
        status="発送可能",
        reason="",
        calculation_mode=mode,
        note=note,
        zone=zone or "",
        source_pdf=str(service.get("source_pdf") or ""),
        source_pages=tuple(int(page) for page in service.get("source_pages", []) if isinstance(page, int)),
        rate_table_weight_g=float(rate.get("max_weight_g", billing_weight_g)),
        effective_from=str(service.get("effective_from") or ""),
        effective_to=str(service.get("effective_to") or ""),
        zonos_applied=bool(zonos_amounts),
        zonos_base_shipping_yen=zonos_amounts.get("base_shipping_yen") if zonos_amounts else None,
        zonos_fee_base_yen=zonos_amounts.get("fee_base_yen") if zonos_amounts else None,
        zonos_fee_rate_percent=zonos_amounts.get("fee_rate_percent") if zonos_amounts else None,
        zonos_fee_yen=zonos_amounts.get("fee_yen") if zonos_amounts else None,
        zonos_duty_rate_percent=zonos_amounts.get("duty_rate_percent") if zonos_amounts else None,
        zonos_duty_base_yen=zonos_amounts.get("duty_base_yen") if zonos_amounts else None,
        zonos_duty_yen=zonos_amounts.get("duty_yen") if zonos_amounts else None,
        zonos_total_shipping_yen=zonos_amounts.get("total_shipping_yen") if zonos_amounts else None,
        zonos_config_effective_from=zonos_amounts.get("effective_from", "") if zonos_amounts else "",
        zonos_config_effective_to=zonos_amounts.get("effective_to", "") if zonos_amounts else "",
        zonos_calculated_at=zonos_amounts.get("calculated_at", "") if zonos_amounts else "",
        zonos_note=zonos_amounts.get("note", "") if zonos_amounts else "",
    )


def unavailable_result(
    result_id: str,
    carrier: str,
    service: str,
    inputs: ProductInputs,
    status: str,
    reason: str,
    *,
    volumetric_weight_g: float | None = None,
    applied_weight_g: float | None = None,
    billing_weight_g: float | None = None,
    zone: str = "",
    source_pdf: str = "",
    source_pages: tuple[int, ...] = (),
    rate_table_weight_g: float | None = None,
    effective_from: str = "",
    effective_to: str = "",
) -> ShippingResult:
    mode = calculation_mode_label(inputs)
    return ShippingResult(
        result_id=result_id,
        carrier=carrier,
        service=service,
        actual_weight_g=inputs.weight_g if inputs.weight_g > 0 else None,
        volumetric_weight_g=volumetric_weight_g,
        applied_weight_g=applied_weight_g,
        billing_weight_g=billing_weight_g,
        base_shipping_yen=None,
        fuel_surcharge_yen=None,
        surcharge_yen=None,
        additional_fee_yen=None,
        other_additional_fee_yen=None,
        total_shipping_yen=None,
        profit_yen=None,
        profit_margin=None,
        shippable=False,
        status=status,
        reason=reason,
        calculation_mode=mode,
        note=reason,
        zone=zone,
        source_pdf=source_pdf,
        source_pages=source_pages,
        rate_table_weight_g=rate_table_weight_g,
        effective_from=effective_from,
        effective_to=effective_to,
    )


def calculate_shipping_results(inputs: ProductInputs) -> list[ShippingResult]:
    rate_book = load_shipping_rate_book()
    results = [
        calculate_one_shipping_result(service, inputs)
        for service in rate_book.get("services", [])
        if (
            str(service.get("carrier") or ""),
            str(service.get("service") or ""),
        )
        not in HIDDEN_SHIPPING_SERVICES
    ]
    available = [result for result in results if result.shippable and result.profit_yen is not None]
    if not available:
        return results

    best_profit = max(result.profit_yen for result in available if result.profit_yen is not None)
    cheapest_shipping = min(result.total_shipping_yen for result in available if result.total_shipping_yen is not None)
    marked_results: list[ShippingResult] = []
    for result in results:
        marked_results.append(
            ShippingResult(
                **{
                    **result.__dict__,
                    "is_recommended": result.profit_yen == best_profit,
                    "is_cheapest": result.total_shipping_yen == cheapest_shipping,
                }
            )
        )
    return marked_results


def sort_results(results: list[ShippingResult], sort_key: str) -> list[ShippingResult]:
    def none_last(value: float | str | None) -> tuple[int, float | str]:
        if value is None:
            return (1, 0)
        return (0, value)

    if sort_key == "利益が高い順":
        return sorted(results, key=lambda item: (item.profit_yen is None, -(item.profit_yen or 0)))
    if sort_key == "送料が安い順":
        return sorted(results, key=lambda item: (item.total_shipping_yen is None, item.total_shipping_yen or 0))
    if sort_key == "利益率が高い順":
        return sorted(results, key=lambda item: (item.profit_margin is None, -(item.profit_margin or 0)))
    return sorted(results, key=lambda item: (item.carrier, item.service, none_last(item.billing_weight_g)))


def shipping_results_table(results: list[ShippingResult]) -> list[dict[str, Any]]:
    rows = []
    for result in results:
        label = ""
        if result.is_recommended:
            label += "おすすめ"
        if result.is_cheapest:
            label += " / 最安送料" if label else "最安送料"
        rows.append(
            {
                "配送会社": result.carrier,
                "サービス名": result.service,
                "実重量(g)": result.actual_weight_g,
                "容積重量(g)": result.volumetric_weight_g,
                "適用重量(g)": result.applied_weight_g,
                "請求重量(g)": result.billing_weight_g,
                "基本送料": result.base_shipping_yen,
                "燃油サーチャージ": result.fuel_surcharge_yen,
                "割増料金": result.surcharge_yen,
                "その他追加料金": (result.additional_fee_yen or 0) + (result.other_additional_fee_yen or 0)
                if result.shippable
                else None,
                "合計送料": result.total_shipping_yen,
                "利益": result.profit_yen,
                "利益率": result.profit_margin,
                "計算区分": result.calculation_mode,
                "発送可否": result.status,
                "発送不可理由": result.reason,
                "注意": result.note,
                "表示": label,
            }
        )
    return rows


def results_csv(results: list[ShippingResult]) -> str:
    output = io.StringIO()
    rows = shipping_results_table(results)
    if not rows:
        return ""
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def short_attention(result: ShippingResult) -> str:
    text = result.reason or result.note or ""
    if result.status == "料金未登録":
        return "料金未登録"
    if not text:
        return "-"
    if "郵便番号" in text:
        return "郵便番号未入力"
    if "対象外" in text:
        return "対象国外"
    if "料金" in text and "登録" in text:
        return "料金未登録"
    if "概算" in text or result.calculation_mode == "実重量のみの概算":
        return "概算"
    if "重量" in text and "超" in text:
        return "重量超過"
    if any(word in text for word in ("サイズ", "長さ", "幅", "高さ", "容積")):
        return "サイズ確認"
    if result.reason:
        return "発送不可"
    return "詳細あり"


def result_detail_html(result: ShippingResult) -> str:
    detail_rows = [
        ("実重量", grams(result.actual_weight_g)),
        ("容積重量", grams(result.volumetric_weight_g)),
        ("適用重量", grams(result.applied_weight_g)),
        ("請求重量", grams(result.billing_weight_g)),
        ("基本送料", compact_yen(result.base_shipping_yen)),
        ("燃油サーチャージ", compact_yen(result.fuel_surcharge_yen)),
        ("割増料金", compact_yen(result.surcharge_yen)),
        (
            "追加料金",
            compact_yen(
                (result.additional_fee_yen or 0) + (result.other_additional_fee_yen or 0)
                if result.shippable
                else None
            ),
        ),
        ("合計送料", compact_yen(result.total_shipping_yen)),
        ("利益", compact_yen(result.profit_yen)),
        ("利益率", percent(result.profit_margin)),
        ("発送可否", html.escape(result.status)),
        ("理由・注意", html.escape(result.reason or result.note or "-")),
    ]
    rows = "".join(
        f"<tr><th>{label}</th><td>{value}</td></tr>"
        for label, value in detail_rows
    )
    return f'<details class="row-detail"><summary>詳細</summary><table>{rows}</table></details>'


def carrier_filter_options() -> tuple[str, ...]:
    return ("すべて", "日本郵便", "SpeedPAK／CPaSS", "FedEx", "DHL")


def carrier_filter_value(label: str) -> str | None:
    if label == "SpeedPAK／CPaSS":
        return "SpeedPAK / CPaSS"
    if label == "すべて":
        return None
    return label


def result_labels(result: ShippingResult, group_results: list[ShippingResult]) -> list[str]:
    labels: list[str] = []
    if result.zonos_applied:
        labels.append("Zonos込み")
    if result.is_recommended:
        labels.append("全体おすすめ")
    if result.is_cheapest:
        labels.append("全体最安")
    selected_id = st.session_state.get("selected_shipping_result_id")
    if selected_id == result.result_id:
        labels.append("選択中")

    available = [item for item in group_results if item.shippable and item.profit_yen is not None]
    if available:
        best_profit = max(item.profit_yen for item in available if item.profit_yen is not None)
        cheapest = min(item.total_shipping_yen for item in available if item.total_shipping_yen is not None)
        if result.profit_yen == best_profit and not result.is_recommended:
            labels.append("会社内おすすめ")
        if result.total_shipping_yen == cheapest and not result.is_cheapest:
            labels.append("会社内最安")
    return labels


def render_label_badges(labels: list[str]) -> None:
    if not labels:
        return
    html_badges = []
    for label in labels:
        css_class = "badge-zonos" if "Zonos" in label else "badge-best" if "おすすめ" in label else "badge-cheap"
        if label == "選択中":
            css_class = "badge-selected"
        html_badges.append(f'<span class="badge {css_class}">{html.escape(label)}</span>')
    st.markdown("".join(html_badges), unsafe_allow_html=True)


def result_summary_label(result: ShippingResult) -> str:
    return (
        f"{result.service} | 送料 {compact_yen(result.total_shipping_yen)} | "
        f"利益 {compact_yen(result.profit_yen)} | 利益率 {percent(result.profit_margin)} | "
        f"{result.status} | {result.calculation_mode}"
    )


def detail_value_card(label: str, value: str, css_class: str = "") -> str:
    return (
        f'<div class="detail-value-card {css_class}">'
        f'<div class="detail-label">{html.escape(label)}</div>'
        f'<div class="detail-value">{html.escape(value)}</div>'
        f"</div>"
    )


def detail_kv_grid(items: list[tuple[str, str]]) -> str:
    cells = "".join(
        f'<div class="detail-kv"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>'
        for label, value in items
    )
    return f'<div class="detail-kv-grid">{cells}</div>'


def detail_breakdown_row(label: str, value: str, css_class: str = "") -> str:
    return (
        f'<div class="breakdown-row {css_class}">'
        f'<span>{html.escape(label)}</span>'
        f'<strong>{html.escape(value)}</strong>'
        f"</div>"
    )


def render_result_detail(inputs: ProductInputs, result: ShippingResult) -> None:
    labels: list[str] = []
    if result.zonos_applied:
        labels.append("Zonos込み")
    if result.is_recommended:
        labels.append("全体おすすめ")
    if result.is_cheapest:
        labels.append("全体最安")
    if st.session_state.get("selected_shipping_result_id") == result.result_id:
        labels.append("選択中")
    label_html = "".join(
        f'<span class="badge {"badge-zonos" if "Zonos" in label else "badge-best" if "おすすめ" in label else "badge-cheap"}">{html.escape(label)}</span>'
        for label in labels
    )
    profit_class = "profit-positive" if (result.profit_yen or 0) >= 0 else "profit-negative"
    summary_html = f"""
    <div class="detail-section">
      <div class="detail-section-title">利益サマリー</div>
      <div class="detail-summary-grid">
        {detail_value_card("合計送料", compact_yen(result.total_shipping_yen), "shipping-value")}
        {detail_value_card("利益", compact_yen(result.profit_yen), profit_class)}
        {detail_value_card("利益率", percent(result.profit_margin), profit_class)}
        {detail_value_card("発送可否", result.status, "status-value")}
      </div>
      <div class="detail-badges">{label_html}</div>
    </div>
    """
    st.markdown(summary_html, unsafe_allow_html=True)

    extra_fees = (
        (result.surcharge_yen or 0)
        + (result.additional_fee_yen or 0)
        + (result.other_additional_fee_yen or 0)
    )
    shipping_rows = [
        detail_breakdown_row("日本郵便基本送料" if result.zonos_applied else "基本送料", compact_yen(result.zonos_base_shipping_yen if result.zonos_applied else result.base_shipping_yen), "shipping-line"),
        detail_breakdown_row("+ Zonos手数料", compact_yen(result.zonos_fee_yen), "zonos-line") if result.zonos_applied else "",
        detail_breakdown_row("+ 関税", compact_yen(result.zonos_duty_yen), "duty-line") if result.zonos_applied else "",
        detail_breakdown_row("+ 燃油サーチャージ", compact_yen(result.fuel_surcharge_yen)),
        detail_breakdown_row("+ 追加料金", compact_yen(extra_fees) if result.shippable else "-"),
        '<div class="breakdown-divider"></div>',
        detail_breakdown_row("合計送料", compact_yen(result.total_shipping_yen), "total-line"),
    ]
    st.markdown(
        f"""
        <div class="detail-section">
          <div class="detail-section-title">送料の内訳</div>
          <div class="shipping-breakdown">{''.join(shipping_rows)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    condition_items = [
        ("配送会社", result.carrier),
        ("サービス名", result.service),
        ("配送先国", inputs.destination_country),
        ("ゾーン", result.zone or "-"),
        ("計算区分", result.calculation_mode),
        ("実重量", grams(result.actual_weight_g)),
        ("容積重量", grams(result.volumetric_weight_g)),
        ("請求重量", grams(result.billing_weight_g)),
        ("料金重量", grams(result.rate_table_weight_g)),
        ("発送可能", result.status),
        ("発送不可理由", result.reason or "-"),
        ("固定手数料（USD）", f"${inputs.fixed_fee_usd:,.2f}"),
        ("固定手数料の為替レート", f"USD/JPY {inputs.usd_jpy_rate:.4f}"),
        ("固定手数料の円換算額", compact_yen(inputs.fixed_fee_usd * inputs.usd_jpy_rate)),
    ]
    st.markdown(
        f"""
        <div class="detail-section">
          <div class="detail-section-title">重量・配送条件</div>
          {detail_kv_grid(condition_items)}
        </div>
        """,
        unsafe_allow_html=True,
    )

    if result.zonos_applied:
        with st.expander("Zonos情報", expanded=False):
            zonos_items = [
                (
                    f"商品価格{inputs.currency_code}",
                    currency_amount(inputs.sale_price_usd, inputs.currency_code),
                ),
                ("商品価格円換算", compact_yen(inputs.sale_price_usd * inputs.exchange_rate)),
                ("為替レート", f"{inputs.currency_code}/JPY {inputs.exchange_rate:.4f}"),
                ("Zonos手数料基準額", compact_yen(result.zonos_fee_base_yen)),
                ("適用された手数料率", f"{result.zonos_fee_rate_percent:.2f}%" if result.zonos_fee_rate_percent is not None else "-"),
                ("関税率", f"{result.zonos_duty_rate_percent:.2f}%" if result.zonos_duty_rate_percent is not None else "-"),
                ("関税対象額", compact_yen(result.zonos_duty_base_yen)),
                ("関税額", compact_yen(result.zonos_duty_yen)),
                ("Zonos込み配送関連費用", compact_yen(result.zonos_total_shipping_yen)),
            ]
            st.markdown(detail_kv_grid(zonos_items), unsafe_allow_html=True)
            if st.button("Zonosの計算式を見る", key=f"zonos_formula_{result.result_id}"):
                st.markdown(
                    detail_kv_grid(
                        [
                            ("計算式", "日本郵便基本送料 + Zonos手数料 + 関税 = Zonos込み配送関連費用"),
                            ("計算日時", result.zonos_calculated_at or "-"),
                            ("発効日", result.zonos_config_effective_from or "-"),
                        ]
                    ),
                    unsafe_allow_html=True,
                )

    with st.expander("システム情報", expanded=False):
        system_items = [
            ("使用した料金表", Path(result.source_pdf).name if result.source_pdf else "-"),
            ("PDFページ", ", ".join(str(page) for page in result.source_pages) if result.source_pages else "-"),
            ("発効日", result.effective_from or "-"),
            ("注意事項", result.note or "-"),
        ]
        st.markdown(detail_kv_grid(system_items), unsafe_allow_html=True)

    registration_ready = (
        result.shippable
        and result.total_shipping_yen is not None
        and result.profit_yen is not None
        and result.profit_margin is not None
    )
    if registration_ready:
        if st.button(
            "この配送方法を選択",
            key=f"select_shipping_{result.result_id}",
            use_container_width=True,
        ):
            st.session_state.selected_shipping_result_id = result.result_id
            st.session_state.pop("registration_shipping_result_id", None)
            st.success(f"{result.carrier} / {result.service} を出品管理登録用に選択しました。")
        if st.button(
            "この配送方法で出品管理ツールへ登録",
            key=f"direct_register_{result.result_id}",
            type="primary",
            width="stretch",
        ):
            st.session_state.selected_shipping_result_id = result.result_id
            st.session_state.pop("registration_shipping_result_id", None)
            submit_listing_registration(
                inputs,
                result,
                source="detail",
            )
    else:
        st.button(
            "この配送方法で出品管理ツールへ登録",
            key=f"direct_register_{result.result_id}",
            type="primary",
            width="stretch",
            disabled=True,
            help=result.reason or result.note or "発送不可または料金未登録です。",
        )
        st.info("この配送方法は発送不可または料金未登録のため、出品管理登録用には選択できません。")


def render_result_card(inputs: ProductInputs, result: ShippingResult, group_results: list[ShippingResult]) -> None:
    with st.container(border=True):
        render_label_badges(result_labels(result, group_results))
        metric_col1, metric_col2, metric_col3, metric_col4 = st.columns([1.5, 1.0, 1.0, 1.0])
        metric_col1.markdown(f"**{result.service}**")
        metric_col1.caption(f"{result.status} / {short_attention(result)}")
        if result.zonos_applied:
            metric_col1.caption("Zonos込み")
        metric_col2.metric("合計送料", compact_yen(result.total_shipping_yen))
        metric_col3.metric("利益", compact_yen(result.profit_yen))
        metric_col4.metric("利益率", percent(result.profit_margin))
        st.caption(f"計算区分: {result.calculation_mode}")
        expanded = bool(result.is_recommended or result.is_cheapest or st.session_state.get("selected_shipping_result_id") == result.result_id)
        with st.expander("詳細を表示", expanded=expanded):
            render_result_detail(inputs, result)


def render_result_group(inputs: ProductInputs, title: str, group_results: list[ShippingResult]) -> None:
    st.markdown(f"#### {title}")
    if not group_results:
        st.info("該当する配送サービスがありません。")
        return
    for result in group_results:
        render_result_card(inputs, result, group_results)


def render_shipping_results_html(results: list[ShippingResult]) -> None:
    headers = [
        "表示",
        "配送会社",
        "サービス名",
        "計算区分",
        "請求重量",
        "合計送料",
        "利益",
        "利益率",
        "発送可否",
        "注意・詳細",
    ]
    body_rows = []
    for result in results:
        badges = []
        if result.is_recommended:
            badges.append('<span class="badge badge-best">おすすめ</span>')
        if result.is_cheapest:
            badges.append('<span class="badge badge-cheap">最安送料</span>')
        if not badges:
            badges.append("")
        cells = [
            "".join(badges),
            html.escape(result.carrier),
            html.escape(result.service),
            html.escape(result.calculation_mode),
            grams(result.billing_weight_g),
            compact_yen(result.total_shipping_yen),
            compact_yen(result.profit_yen),
            percent(result.profit_margin),
            html.escape(result.status),
            f'<span class="attention-pill">{html.escape(short_attention(result))}</span>{result_detail_html(result)}',
        ]
        body_rows.append(
            "<tr>"
            + "".join(
                f'<td data-label="{html.escape(header)}" class="money-cell profit-cell">{cell}</td>'
                if header == "利益"
                else f'<td data-label="{html.escape(header)}" class="money-cell">{cell}</td>'
                if header in ("合計送料", "利益率")
                else f'<td data-label="{html.escape(header)}">{cell}</td>'
                for header, cell in zip(headers, cells)
            )
            + "</tr>"
        )

    header_html = "".join(
        f'<th class="profit-cell">{html.escape(header)}</th>' if header == "利益" else f"<th>{html.escape(header)}</th>"
        for header in headers
    )
    table_html = f"""
    <div class="comparison-common-note">サイズ未入力時は、実重量のみを使用した概算料金です。詳細は各行の「詳細」から確認できます。</div>
    <div class="comparison-table-wrap">
      <table class="comparison-table">
        <thead><tr>{header_html}</tr></thead>
        <tbody>{''.join(body_rows)}</tbody>
      </table>
    </div>
    """
    st.markdown(table_html, unsafe_allow_html=True)


def validate_registration(
    inputs: ProductInputs,
    selected_result: ShippingResult | None,
) -> list[str]:
    missing = []
    if not inputs.product_name.strip():
        missing.append("商品名")
    if inputs.sale_price_usd <= 0:
        missing.append("販売価格")
    if inputs.purchase_price_yen <= 0:
        missing.append("仕入れ価格")
    if inputs.weight_g <= 0:
        missing.append("重量")
    if not inputs.destination_country.strip():
        missing.append("配送先国")
    if selected_result is None:
        missing.append("選択した配送方法")
    elif not selected_result.shippable:
        missing.append("発送可能な配送方法")
    elif selected_result.total_shipping_yen is None:
        missing.append("送料")
    elif selected_result.profit_yen is None:
        missing.append("利益")
    elif selected_result.profit_margin is None:
        missing.append("利益率")
    return missing


def shipping_breakdown_payload(result: ShippingResult, calculated_at: str) -> dict[str, Any]:
    total_yen = float(result.total_shipping_yen or 0)
    base_shipping_yen = float(
        result.zonos_base_shipping_yen
        if result.zonos_applied and result.zonos_base_shipping_yen is not None
        else result.base_shipping_yen or 0
    )
    fuel_surcharge_yen = float(result.fuel_surcharge_yen or 0)
    surcharge_yen = float(result.surcharge_yen or 0)
    additional_fee_yen = float(result.additional_fee_yen or 0)
    other_additional_fee_yen = float(result.other_additional_fee_yen or 0)
    zonos_fee_yen = float(result.zonos_fee_yen or 0)
    zonos_duty_yen = float(result.zonos_duty_yen or 0)
    visible_total = (
        base_shipping_yen
        + fuel_surcharge_yen
        + surcharge_yen
        + additional_fee_yen
        + other_additional_fee_yen
        + zonos_fee_yen
        + zonos_duty_yen
    )
    adjustment_yen = round(total_yen - visible_total)

    items: list[dict[str, Any]] = []

    def add_item(label: str, amount_yen: float) -> None:
        if round(amount_yen) != 0:
            items.append({"label": label, "amount_yen": round(amount_yen)})

    add_item("日本郵便基本送料" if result.zonos_applied else "基本送料", base_shipping_yen)
    if result.zonos_applied:
        add_item("Zonos手数料", zonos_fee_yen)
        add_item("関税", zonos_duty_yen)
    add_item("燃油サーチャージ", fuel_surcharge_yen)
    add_item("割増料金", surcharge_yen)
    add_item("追加料金", additional_fee_yen + other_additional_fee_yen)
    add_item("その他追加料金", adjustment_yen)

    return {
        "carrier": result.carrier,
        "service": result.service,
        "items": items,
        "base_shipping_yen": round(base_shipping_yen),
        "fuel_surcharge_yen": round(fuel_surcharge_yen),
        "surcharge_yen": round(surcharge_yen),
        "additional_fee_yen": round(additional_fee_yen),
        "other_additional_fee_yen": round(other_additional_fee_yen),
        "additional_total_yen": round(surcharge_yen + additional_fee_yen + other_additional_fee_yen + adjustment_yen),
        "total_yen": round(total_yen),
        "actual_weight_g": result.actual_weight_g,
        "volumetric_weight_g": result.volumetric_weight_g,
        "applied_weight_g": result.applied_weight_g,
        "billing_weight_g": result.billing_weight_g,
        "rate_table_weight_g": result.rate_table_weight_g,
        "status": result.status,
        "reason": result.reason,
        "calculation_mode": result.calculation_mode,
        "destination_country": "",
        "zonos_applied": result.zonos_applied,
        "zonos_fee_yen": round(zonos_fee_yen),
        "zonos_duty_yen": round(zonos_duty_yen),
        "source_pdf": result.source_pdf,
        "source_pages": list(result.source_pages),
        "effective_from": result.effective_from,
        "effective_to": result.effective_to,
        "calculated_at": calculated_at,
    }


def append_registration_log(event: str, details: dict[str, Any]) -> None:
    entry = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "event": event,
        **details,
    }
    line = json.dumps(entry, ensure_ascii=False, default=str)
    print(f"[listing-registration] {line}", flush=True)
    try:
        REGISTRATION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with REGISTRATION_LOG_PATH.open("a", encoding="utf-8") as log_file:
            log_file.write(line + "\n")
    except OSError as exc:
        print(f"[listing-registration] log write failed: {exc}", flush=True)


def publish_registration_event(details: dict[str, Any]) -> str | None:
    try:
        REGISTRATION_EVENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "event_id": f"{details.get('listing_id', 'unknown')}-{time.time_ns()}",
            "published_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            **details,
        }
        temporary_path = REGISTRATION_EVENT_PATH.with_name(
            f".{REGISTRATION_EVENT_PATH.name}.{time.time_ns()}.tmp"
        )
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        temporary_path.replace(REGISTRATION_EVENT_PATH)
        return None
    except OSError as exc:
        return str(exc)


def _register_listing(
    inputs: ProductInputs,
    selected_result: ShippingResult,
) -> RegistrationOutcome:
    init_listing_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sale_price_yen = inputs.sale_price_usd * inputs.exchange_rate
    gross_sales_yen = inputs.sale_price_usd * inputs.exchange_rate
    ebay_fee_yen = gross_sales_yen * inputs.ebay_fee_rate / 100
    overseas_fee_yen = gross_sales_yen * inputs.overseas_fee_rate / 100
    ad_fee_yen = gross_sales_yen * inputs.ad_rate / 100
    fixed_fee_yen = inputs.fixed_fee_usd * inputs.usd_jpy_rate
    roi = (
        selected_result.profit_yen / inputs.purchase_price_yen * 100
        if inputs.purchase_price_yen > 0 and selected_result.profit_yen is not None
        else None
    )
    shipping_breakdown = shipping_breakdown_payload(selected_result, now)
    shipping_breakdown["destination_country"] = inputs.destination_country
    shipping_breakdown["currency_code"] = inputs.currency_code
    shipping_breakdown["product_exchange_rate"] = inputs.exchange_rate
    shipping_breakdown["usd_jpy_rate"] = inputs.usd_jpy_rate

    data = {
        "product_name": inputs.product_name.strip(),
        "platform": PLATFORM_EBAY,
        "currency_code": inputs.currency_code,
        "usd_jpy_rate": inputs.usd_jpy_rate,
        "listing_date": date.today().isoformat(),
        "listing_price_usd": inputs.sale_price_usd,
        "listing_price": inputs.sale_price_usd,
        "buyer_shipping_usd": 0.0,
        "exchange_rate": inputs.exchange_rate,
        "purchase_price_yen": inputs.purchase_price_yen,
        "purchase_price": inputs.purchase_price_yen,
        "domestic_shipping_yen": inputs.domestic_shipping_yen,
        "international_shipping_yen": selected_result.total_shipping_yen or 0.0,
        "packaging_yen": inputs.packaging_yen,
        "other_cost_yen": inputs.other_fee_yen,
        "expected_shipping": selected_result.total_shipping_yen or 0.0,
        "ebay_fee_yen": ebay_fee_yen,
        "ebay_fee_rate": inputs.ebay_fee_rate,
        "ad_fee_yen": ad_fee_yen,
        "promoted_listing_rate": inputs.ad_rate,
        "exchange_spread_rate": inputs.overseas_fee_rate,
        "fixed_fee_usd": inputs.fixed_fee_usd,
        "target_profit_yen": inputs.target_profit_yen,
        "expected_profit_yen": selected_result.profit_yen or 0.0,
        "profit_yen": selected_result.profit_yen or 0.0,
        "profit_margin": selected_result.profit_margin or 0.0,
        "roi": roi,
        "gross_sales_yen": gross_sales_yen,
        "break_even_sale_price_usd": None,
        "target_sale_price_usd": None,
        "search_keyword": "",
        "monthly_sales": 0.0,
        "competitor_count": 0.0,
        "product_url": inputs.product_url.strip(),
        "research_shipping_weight_g": inputs.weight_g,
        "inventory_risk": "",
        "research_memo": selected_result.calculation_mode,
        "calculated_at": now,
        "status": STATUS_ACTIVE,
        "sku": inputs.sku.strip(),
        "source_url": inputs.source_url.strip(),
        "destination_country": inputs.destination_country,
        "destination_postal_code": inputs.postal_code.strip(),
        "sale_price_yen": sale_price_yen,
        "package_weight_g": inputs.weight_g,
        "package_length_cm": inputs.length_cm,
        "package_width_cm": inputs.width_cm,
        "package_height_cm": inputs.height_cm,
        "expected_shipping_carrier": selected_result.carrier,
        "expected_shipping_service": selected_result.service,
        "planned_shipping_yen": selected_result.total_shipping_yen or 0.0,
        "planned_profit_margin": selected_result.profit_margin or 0.0,
        "planned_base_shipping_yen": selected_result.base_shipping_yen or 0.0,
        "planned_fuel_surcharge_yen": selected_result.fuel_surcharge_yen or 0.0,
        "planned_additional_fee_yen": shipping_breakdown["additional_total_yen"],
        "planned_shipping_status": selected_result.status,
        "planned_shipping_reason": selected_result.reason,
        "rate_table_weight_g": selected_result.rate_table_weight_g,
        "shipping_breakdown_json": json.dumps(shipping_breakdown, ensure_ascii=False),
        "shipping_carrier": selected_result.carrier,
        "shipping_service": selected_result.service,
        "shipping_weight_g": inputs.weight_g,
        "overseas_fee_rate": inputs.overseas_fee_rate,
        "overseas_fee_yen": overseas_fee_yen,
        "other_fee_yen": inputs.other_fee_yen,
        "shipping_calculation_mode": selected_result.calculation_mode,
        "volumetric_weight_g": selected_result.volumetric_weight_g,
        "applied_weight_g": selected_result.applied_weight_g,
        "billing_weight_g": selected_result.billing_weight_g,
        "zonos_applied": 1 if selected_result.zonos_applied else 0,
        "zonos_base_shipping_yen": selected_result.zonos_base_shipping_yen or 0.0,
        "zonos_fee_base_yen": selected_result.zonos_fee_base_yen or 0.0,
        "zonos_fee_rate_percent": selected_result.zonos_fee_rate_percent or 0.0,
        "zonos_fee_yen": selected_result.zonos_fee_yen or 0.0,
        "zonos_duty_rate_percent": selected_result.zonos_duty_rate_percent or 0.0,
        "zonos_duty_base_yen": selected_result.zonos_duty_base_yen or 0.0,
        "zonos_duty_yen": selected_result.zonos_duty_yen or 0.0,
        "zonos_total_shipping_yen": selected_result.zonos_total_shipping_yen or 0.0,
        "zonos_config_effective_from": selected_result.zonos_config_effective_from,
        "zonos_config_effective_to": selected_result.zonos_config_effective_to,
        "registered_at": now,
        "platform_memo": inputs.memo.strip(),
        "created_at": now,
        "updated_at": now,
    }
    columns = list(data.keys())
    placeholders = ", ".join("?" for _ in columns)
    column_list = ", ".join(columns)

    database_path = database_location_label(LISTING_DB_PATH)
    try:
        with get_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                f"INSERT INTO listings ({column_list}) VALUES ({placeholders})",
                tuple(data[column] for column in columns),
            )
            listing_id = int(cursor.lastrowid)
            connection.commit()

        with get_connection() as verification_connection:
            saved_row = verification_connection.execute(
                """
                SELECT id, product_name, expected_shipping_carrier,
                       expected_shipping_service, planned_shipping_yen,
                       expected_profit_yen, currency_code, exchange_rate,
                       usd_jpy_rate, created_at
                FROM listings
                WHERE id = ?
                """,
                (listing_id,),
            ).fetchone()
            total_count = int(
                verification_connection.execute(
                    "SELECT COUNT(*) FROM listings"
                ).fetchone()[0]
            )
        if saved_row is None:
            raise RuntimeError(
                f"INSERT後の確認でID {listing_id} が見つかりませんでした。"
            )
        if str(saved_row["product_name"]) != inputs.product_name.strip():
            raise RuntimeError(
                f"保存確認時の商品名が一致しません。ID: {listing_id}"
            )
        if normalize_currency(saved_row["currency_code"]) != inputs.currency_code:
            raise RuntimeError(
                f"保存確認時の販売通貨が一致しません。ID: {listing_id}"
            )

        event_details = {
            "listing_id": listing_id,
            "total_count": total_count,
            "database_path": database_path,
            "product_name": inputs.product_name.strip(),
            "carrier": selected_result.carrier,
            "service": selected_result.service,
            "sale_price_usd": inputs.sale_price_usd,
            "sale_price_foreign": inputs.sale_price_usd,
            "currency_code": inputs.currency_code,
            "exchange_rate": inputs.exchange_rate,
            "usd_jpy_rate": inputs.usd_jpy_rate,
            "planned_shipping_yen": selected_result.total_shipping_yen,
            "planned_profit_yen": selected_result.profit_yen,
        }
        notification_error = publish_registration_event(event_details)
        append_registration_log(
            "registration_succeeded",
            {**event_details, "notification_error": notification_error},
        )
        return RegistrationOutcome(
            success=True,
            error=None,
            notification_error=notification_error,
            listing_id=listing_id,
            total_count=total_count,
            database_path=database_path,
            product_name=inputs.product_name.strip(),
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        append_registration_log(
            "registration_failed",
            {
                "database_path": database_path,
                "product_name": inputs.product_name.strip(),
                "carrier": selected_result.carrier,
                "service": selected_result.service,
                "error": error,
            },
        )
        return RegistrationOutcome(
            success=False,
            error=error,
            notification_error=None,
            listing_id=None,
            total_count=0,
            database_path=database_path,
            product_name=inputs.product_name.strip(),
        )


def register_listing(
    inputs: ProductInputs,
    selected_result: ShippingResult,
) -> RegistrationOutcome:
    """Register a listing and always return a user-displayable result."""
    try:
        return _register_listing(inputs, selected_result)
    except Exception as exc:
        database_path = database_location_label(LISTING_DB_PATH)
        error = f"{type(exc).__name__}: {exc}"
        append_registration_log(
            "registration_failed_before_insert",
            {
                "database_path": database_path,
                "product_name": inputs.product_name.strip(),
                "carrier": selected_result.carrier,
                "service": selected_result.service,
                "error": error,
            },
        )
        return RegistrationOutcome(
            success=False,
            error=error,
            notification_error=None,
            listing_id=None,
            total_count=0,
            database_path=database_path,
            product_name=inputs.product_name.strip(),
        )


def registration_fingerprint(
    inputs: ProductInputs,
    selected_result: ShippingResult,
) -> str:
    """Identify an identical UI registration without changing the DB schema."""
    shipping_result = dict(selected_result.__dict__)
    shipping_result.pop("zonos_calculated_at", None)
    return json.dumps(
        {
            "inputs": inputs.__dict__,
            "shipping_result": shipping_result,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def submit_listing_registration(
    inputs: ProductInputs,
    selected_result: ShippingResult | None,
    *,
    source: str,
) -> RegistrationOutcome | None:
    """Validate, deduplicate, save, and render feedback for every eBay entry point."""
    missing = validate_registration(inputs, selected_result)
    if missing:
        st.error("登録に必要な項目が不足しています: " + "、".join(missing))
        return None

    assert selected_result is not None
    fingerprint = registration_fingerprint(inputs, selected_result)
    now_monotonic = time.monotonic()
    previous = st.session_state.get("_last_listing_registration")
    if isinstance(previous, dict):
        previous_fingerprint = previous.get("fingerprint")
        previous_at = previous.get("monotonic")
        if (
            previous_fingerprint == fingerprint
            and isinstance(previous_at, (int, float))
            and now_monotonic - float(previous_at)
            < REGISTRATION_DEDUP_WINDOW_SECONDS
        ):
            st.warning(
                "同じ商品・配送方法は直前に登録済みです。"
                "二重登録を防止したため、追加保存しませんでした。"
            )
            append_registration_log(
                "registration_duplicate_blocked",
                {
                    "source": source,
                    "product_name": inputs.product_name.strip(),
                    "carrier": selected_result.carrier,
                    "service": selected_result.service,
                    "listing_id": previous.get("listing_id"),
                },
            )
            return None

    outcome = register_listing(inputs, selected_result)
    if outcome.success:
        st.session_state["_last_listing_registration"] = {
            "fingerprint": fingerprint,
            "monotonic": now_monotonic,
            "listing_id": outcome.listing_id,
        }
        append_registration_log(
            "registration_ui_completed",
            {
                "source": source,
                "listing_id": outcome.listing_id,
                "total_count": outcome.total_count,
                "database_path": outcome.database_path,
                "product_name": outcome.product_name,
                "carrier": selected_result.carrier,
                "service": selected_result.service,
            },
        )
        if source == "detail":
            st.success(
                f"{selected_result.carrier} {selected_result.service}の配送方法で"
                "出品管理ツールへ登録しました。"
                f" 保存ID: {outcome.listing_id} / 保存後の総件数: {outcome.total_count}件"
            )
        else:
            st.success(
                f"出品管理ツールへ登録しました。保存ID: {outcome.listing_id} / "
                f"保存後の総件数: {outcome.total_count}件"
            )
        st.info(
            f"登録内容: {outcome.product_name} / "
            f"{selected_result.carrier} {selected_result.service}\n\n"
            f"保存先: `{outcome.database_path}`"
        )
        if outcome.notification_error:
            st.warning(
                "データは保存されましたが、一覧の自動更新通知を作成できませんでした。"
                f"出品管理側の更新ボタンを押してください。詳細: {outcome.notification_error}"
            )
    else:
        st.error(
            "出品管理ツールへの登録に失敗しました。\n\n"
            f"保存先: `{outcome.database_path}`\n\n"
            f"詳細: {outcome.error}"
        )
    return outcome


def register_simple_listing(
    inputs: SimpleProfitInputs,
    result: SimpleProfitCalculation,
) -> RegistrationOutcome:
    init_listing_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_iphone_resale = inputs.platform == PLATFORM_IPHONE_RESALE
    stored_other_cost_yen = 0.0 if is_iphone_resale else inputs.other_cost_yen
    stored_fee_rate = (
        0.0
        if is_iphone_resale
        else inputs.fee_rate_percent
        if inputs.fee_input_mode == FEE_MODE_RATE
        else 0.0
    )
    shipping_breakdown = {
        "carrier": "",
        "service": "",
        "items": (
            [{"label": "送料", "amount_yen": inputs.shipping_yen}]
            if inputs.shipping_yen
            else []
        ),
        "total_yen": inputs.shipping_yen,
        "calculated_at": now,
        "destination_country": "日本",
    }
    data = {
        "product_name": inputs.product_name.strip(),
        "platform": inputs.platform,
        "currency_code": "JPY",
        "usd_jpy_rate": 0.0,
        "listing_date": date.today().isoformat(),
        "listing_price_usd": inputs.sale_price_yen,
        "listing_price": inputs.sale_price_yen,
        "buyer_shipping_usd": 0.0,
        "exchange_rate": 1.0,
        "purchase_price_yen": inputs.purchase_price_yen,
        "purchase_price": inputs.purchase_price_yen,
        "domestic_shipping_yen": 0.0,
        "international_shipping_yen": inputs.shipping_yen,
        "packaging_yen": 0.0,
        "other_cost_yen": stored_other_cost_yen,
        "expected_shipping": inputs.shipping_yen,
        "ebay_fee_yen": result.sales_fee_yen,
        "ebay_fee_rate": stored_fee_rate,
        "ad_fee_yen": 0.0,
        "promoted_listing_rate": 0.0,
        "exchange_spread_rate": 0.0,
        "fixed_fee_usd": 0.0,
        "target_profit_yen": 0.0,
        "expected_profit_yen": result.profit_yen,
        "profit_yen": result.profit_yen,
        "profit_margin": result.profit_margin,
        "roi": result.roi,
        "gross_sales_yen": inputs.sale_price_yen,
        "break_even_sale_price_usd": None,
        "target_sale_price_usd": None,
        "search_keyword": "",
        "monthly_sales": 0.0,
        "competitor_count": 0.0,
        "product_url": "",
        "research_shipping_weight_g": 0.0,
        "inventory_risk": "",
        "research_memo": inputs.memo.strip(),
        "calculated_at": now,
        "status": STATUS_ACTIVE,
        "sku": "",
        "source_url": "",
        "destination_country": "日本",
        "destination_postal_code": "",
        "sale_price_yen": inputs.sale_price_yen,
        "package_weight_g": 0.0,
        "package_length_cm": 0.0,
        "package_width_cm": 0.0,
        "package_height_cm": 0.0,
        "expected_shipping_carrier": "",
        "expected_shipping_service": "",
        "planned_shipping_yen": inputs.shipping_yen,
        "planned_profit_margin": result.profit_margin,
        "planned_base_shipping_yen": inputs.shipping_yen,
        "planned_fuel_surcharge_yen": 0.0,
        "planned_additional_fee_yen": 0.0,
        "planned_shipping_status": "",
        "planned_shipping_reason": "",
        "rate_table_weight_g": None,
        "shipping_breakdown_json": json.dumps(
            shipping_breakdown,
            ensure_ascii=False,
        ),
        "shipping_carrier": "",
        "shipping_service": "",
        "shipping_weight_g": None,
        "overseas_fee_rate": 0.0,
        "overseas_fee_yen": 0.0,
        "other_fee_yen": stored_other_cost_yen,
        "shipping_calculation_mode": "",
        "volumetric_weight_g": None,
        "applied_weight_g": None,
        "billing_weight_g": None,
        "zonos_applied": 0,
        "zonos_base_shipping_yen": 0.0,
        "zonos_fee_base_yen": 0.0,
        "zonos_fee_rate_percent": 0.0,
        "zonos_fee_yen": 0.0,
        "zonos_duty_rate_percent": 0.0,
        "zonos_duty_base_yen": 0.0,
        "zonos_duty_yen": 0.0,
        "zonos_total_shipping_yen": 0.0,
        "zonos_config_effective_from": "",
        "zonos_config_effective_to": "",
        "registered_at": now,
        "sales_fee_input_mode": (
            FEE_MODE_AMOUNT if is_iphone_resale else inputs.fee_input_mode
        ),
        "sales_fee_rate": stored_fee_rate,
        "sales_fee_yen": result.sales_fee_yen,
        "simple_shipping_yen": inputs.shipping_yen,
        "repair_cost_yen": 0.0 if is_iphone_resale else inputs.repair_cost_yen,
        "parts_cost_yen": 0.0 if is_iphone_resale else inputs.parts_cost_yen,
        "iphone_model": inputs.iphone_model.strip(),
        "iphone_capacity": inputs.iphone_capacity.strip(),
        "platform_memo": inputs.memo.strip(),
        "created_at": now,
        "updated_at": now,
    }
    columns = list(data)
    database_path = database_location_label(LISTING_DB_PATH)
    try:
        with get_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                f"INSERT INTO listings ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                tuple(data[column] for column in columns),
            )
            listing_id = int(cursor.lastrowid)
            connection.commit()

        with get_connection() as verification_connection:
            saved_row = verification_connection.execute(
                """
                SELECT id, product_name, platform, expected_profit_yen
                FROM listings
                WHERE id = ?
                """,
                (listing_id,),
            ).fetchone()
            total_count = int(
                verification_connection.execute(
                    "SELECT COUNT(*) FROM listings"
                ).fetchone()[0]
            )
        if saved_row is None:
            raise RuntimeError(
                f"INSERT後の確認でID {listing_id} が見つかりませんでした。"
            )
        if str(saved_row["platform"]) != inputs.platform:
            raise RuntimeError(
                f"保存確認時の販売プラットフォームが一致しません。ID: {listing_id}"
            )

        event_details = {
            "listing_id": listing_id,
            "total_count": total_count,
            "database_path": database_path,
            "product_name": inputs.product_name.strip(),
            "platform": inputs.platform,
            "sale_price_yen": inputs.sale_price_yen,
            "planned_shipping_yen": inputs.shipping_yen,
            "planned_profit_yen": result.profit_yen,
        }
        notification_error = publish_registration_event(event_details)
        append_registration_log(
            "registration_succeeded",
            {**event_details, "notification_error": notification_error},
        )
        return RegistrationOutcome(
            success=True,
            error=None,
            notification_error=notification_error,
            listing_id=listing_id,
            total_count=total_count,
            database_path=database_path,
            product_name=inputs.product_name.strip(),
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        append_registration_log(
            "registration_failed",
            {
                "database_path": database_path,
                "product_name": inputs.product_name.strip(),
                "platform": inputs.platform,
                "error": error,
            },
        )
        return RegistrationOutcome(
            success=False,
            error=error,
            notification_error=None,
            listing_id=None,
            total_count=0,
            database_path=database_path,
            product_name=inputs.product_name.strip(),
        )


def inject_compact_css() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 1420px;
            padding-top: 0.65rem;
            padding-bottom: 4rem;
        }
        h1 {
            font-size: 1.45rem !important;
            line-height: 1.25 !important;
            margin: 0 0 0.1rem 0 !important;
        }
        h2, h3 {
            font-size: 1.02rem !important;
            line-height: 1.25 !important;
            margin: 0.25rem 0 0.2rem 0 !important;
        }
        div[data-testid="stCaptionContainer"] {
            font-size: 0.8rem;
            margin-bottom: 0.1rem;
        }
        div[data-testid="stVerticalBlock"] {
            gap: 0.35rem;
        }
        div[data-testid="stHorizontalBlock"] {
            gap: 0.55rem;
        }
        div[data-testid="stNumberInput"] label,
        div[data-testid="stTextInput"] label,
        div[data-testid="stSelectbox"] label,
        div[data-testid="stRadio"] label {
            font-size: 0.82rem;
            line-height: 1.2;
            padding-bottom: 0.05rem;
        }
        div[data-testid="stNumberInput"] input,
        div[data-testid="stTextInput"] input {
            min-height: 2rem;
            padding-top: 0.25rem;
            padding-bottom: 0.25rem;
        }
        div[data-testid="stButton"] button,
        div[data-testid="stDownloadButton"] button {
            min-height: 2.05rem;
            padding: 0.25rem 0.75rem;
        }
        .compact-section {
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 0.55rem 0.7rem 0.7rem;
            margin-bottom: 0.45rem;
            background: #ffffff;
        }
        .summary-card {
            border: 1px solid #d8dee4;
            border-radius: 8px;
            padding: 0.65rem 0.75rem;
            margin: 0.2rem 0 0.5rem;
            background: #fbfcfe;
            height: auto;
            overflow: visible;
            white-space: normal;
        }
        .summary-title {
            font-size: 0.82rem;
            color: #475569;
            margin-bottom: 0.2rem;
            line-height: 1.3;
        }
        .summary-service {
            font-weight: 700;
            font-size: 0.98rem;
            line-height: 1.35;
            color: #111827;
            overflow-wrap: anywhere;
            white-space: normal;
            margin-bottom: 0.35rem;
        }
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(120px, 1fr));
            gap: 0.45rem;
        }
        .summary-mini {
            border-radius: 6px;
            background: #f3f6fa;
            padding: 0.45rem 0.5rem;
            min-height: auto;
        }
        .summary-mini-label {
            font-size: 0.72rem;
            color: #64748b;
            line-height: 1.2;
        }
        .summary-mini-value {
            font-size: 0.94rem;
            font-weight: 700;
            color: #111827;
            line-height: 1.3;
            white-space: normal;
            overflow-wrap: anywhere;
        }
        .summary-note {
            font-size: 0.78rem;
            color: #64748b;
            line-height: 1.35;
            margin-top: 0.35rem;
        }
        .comparison-common-note {
            font-size: 0.76rem;
            color: #64748b;
            margin: 0.15rem 0 0.35rem;
        }
        .comparison-table-wrap {
            width: 100%;
            max-width: 100%;
            overflow-x: visible;
            overflow-y: visible;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            margin-bottom: 0.75rem;
        }
        .comparison-table {
            border-collapse: collapse;
            width: 100%;
            min-width: 0;
            font-size: 0.76rem;
            table-layout: fixed;
        }
        .comparison-table th,
        .comparison-table td {
            border-bottom: 1px solid #edf0f2;
            padding: 0.28rem 0.34rem;
            text-align: left;
            vertical-align: top;
            line-height: 1.25;
            white-space: normal;
            overflow-wrap: anywhere;
        }
        .comparison-table th {
            background: #f8fafc;
            font-weight: 700;
            color: #334155;
            position: sticky;
            top: 0;
            z-index: 1;
        }
        .comparison-table .profit-cell {
            min-width: 96px;
            white-space: nowrap;
            font-weight: 700;
            font-variant-numeric: tabular-nums;
        }
        .comparison-table .money-cell {
            white-space: nowrap;
            font-weight: 700;
            font-variant-numeric: tabular-nums;
        }
        .comparison-table th:nth-child(1), .comparison-table td:nth-child(1) { width: 9%; }
        .comparison-table th:nth-child(2), .comparison-table td:nth-child(2) { width: 10%; }
        .comparison-table th:nth-child(3), .comparison-table td:nth-child(3) { width: 20%; }
        .comparison-table th:nth-child(4), .comparison-table td:nth-child(4) { width: 12%; }
        .comparison-table th:nth-child(5), .comparison-table td:nth-child(5) { width: 8%; }
        .comparison-table th:nth-child(6), .comparison-table td:nth-child(6) { width: 10%; }
        .comparison-table th:nth-child(7), .comparison-table td:nth-child(7) { width: 10%; }
        .comparison-table th:nth-child(8), .comparison-table td:nth-child(8) { width: 7%; }
        .comparison-table th:nth-child(9), .comparison-table td:nth-child(9) { width: 7%; }
        .comparison-table th:nth-child(10), .comparison-table td:nth-child(10) { width: 7%; }
        .attention-pill {
            display: inline-block;
            border-radius: 999px;
            background: #f1f5f9;
            color: #334155;
            padding: 0.08rem 0.35rem;
            font-size: 0.68rem;
            font-weight: 700;
            white-space: nowrap;
            margin-bottom: 0.1rem;
        }
        .row-detail summary {
            cursor: pointer;
            color: #2563eb;
            font-size: 0.7rem;
            line-height: 1.2;
            white-space: nowrap;
        }
        .row-detail table {
            width: 100%;
            margin-top: 0.25rem;
            border-collapse: collapse;
            font-size: 0.72rem;
        }
        .row-detail th,
        .row-detail td {
            border-bottom: 1px solid #eef2f7;
            padding: 0.16rem 0.2rem;
        }
        .row-detail th {
            width: 38%;
            color: #64748b;
            font-weight: 700;
        }
        .badge {
            display: inline-block;
            border-radius: 999px;
            padding: 0.08rem 0.34rem;
            font-size: 0.66rem;
            font-weight: 700;
            margin: 0.04rem 0.08rem 0.04rem 0;
            white-space: nowrap;
        }
        .badge-best {
            background: #e0f2fe;
            color: #075985;
        }
        .badge-cheap {
            background: #dcfce7;
            color: #166534;
        }
        .badge-zonos {
            background: #cffafe;
            color: #0e7490;
        }
        .badge-selected {
            background: #fef3c7;
            color: #92400e;
        }
        .detail-section {
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            padding: 0.85rem;
            margin: 0.7rem 0;
            background: #ffffff;
        }
        .detail-section-title {
            font-weight: 800;
            font-size: 0.98rem;
            color: #0f172a;
            margin-bottom: 0.65rem;
        }
        .detail-summary-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.65rem;
        }
        .detail-value-card {
            border: 1px solid #e5e7eb;
            border-radius: 9px;
            padding: 0.7rem;
            background: #f8fafc;
            min-height: 76px;
        }
        .detail-label {
            color: #94a3b8;
            font-size: 0.74rem;
            font-weight: 700;
            margin-bottom: 0.25rem;
        }
        .detail-value {
            color: #111827;
            font-size: 1.22rem;
            font-weight: 850;
            line-height: 1.18;
            overflow-wrap: anywhere;
        }
        .shipping-value .detail-value,
        .shipping-line strong,
        .total-line strong {
            color: #2563eb;
        }
        .profit-positive .detail-value {
            color: #16a34a;
        }
        .profit-negative .detail-value {
            color: #dc2626;
        }
        .status-value .detail-value {
            color: #334155;
            font-size: 1rem;
        }
        .detail-badges {
            margin-top: 0.55rem;
        }
        .shipping-breakdown {
            max-width: 620px;
        }
        .breakdown-row {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 1rem;
            padding: 0.42rem 0;
            border-bottom: 1px solid #f1f5f9;
        }
        .breakdown-row span {
            color: #94a3b8;
            font-size: 0.82rem;
            font-weight: 700;
        }
        .breakdown-row strong {
            color: #0f172a;
            font-size: 1.05rem;
            font-weight: 850;
            font-variant-numeric: tabular-nums;
        }
        .zonos-line strong {
            color: #0891b2;
        }
        .duty-line strong {
            color: #ea580c;
        }
        .breakdown-divider {
            border-top: 2px solid #cbd5e1;
            margin: 0.35rem 0;
        }
        .total-line {
            border-bottom: 0;
            padding-top: 0.55rem;
        }
        .total-line span,
        .total-line strong {
            font-size: 1.15rem;
        }
        .detail-kv-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.55rem;
        }
        .detail-kv {
            border: 1px solid #edf2f7;
            border-radius: 8px;
            padding: 0.55rem 0.65rem;
            background: #f8fafc;
        }
        .detail-kv span {
            display: block;
            color: #94a3b8;
            font-size: 0.72rem;
            font-weight: 700;
            margin-bottom: 0.22rem;
        }
        .detail-kv strong {
            display: block;
            color: #1f2937;
            font-size: 0.9rem;
            line-height: 1.25;
            overflow-wrap: anywhere;
        }
        .simple-profit-card {
            border: 1px solid #d8dee4;
            border-radius: 8px;
            padding: 0.85rem 1rem;
            margin: 0.45rem 0 0.75rem;
            background: #fbfcfe;
        }
        .simple-profit-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(120px, 1fr));
            gap: 0.65rem;
        }
        .simple-profit-label {
            color: #64748b;
            font-size: 0.78rem;
            margin-bottom: 0.15rem;
        }
        .simple-profit-value {
            color: #111827;
            font-size: 1.18rem;
            font-weight: 700;
            white-space: nowrap;
        }
        .simple-profit-value.positive {
            color: #15803d;
        }
        .simple-profit-value.negative {
            color: #b91c1c;
        }
        .mobile-registration-selection {
            display: none;
        }
        .bottom-spacer {
            height: 2.25rem;
        }
        @media (max-width: 768px) {
            html,
            body,
            [data-testid="stAppViewContainer"],
            [data-testid="stMain"] {
                max-width: 100%;
                overflow-x: hidden;
            }
            .block-container {
                width: 100%;
                max-width: 100%;
                padding: 0.5rem 0.7rem 4rem;
            }
            h1 {
                font-size: 1.25rem !important;
            }
            h2, h3 {
                font-size: 1rem !important;
            }
            div[data-testid="stHorizontalBlock"] {
                flex-direction: column !important;
                gap: 0.45rem !important;
                width: 100% !important;
            }
            div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
                width: 100% !important;
                min-width: 100% !important;
                flex: 1 1 100% !important;
            }
            div[data-testid="stNumberInput"],
            div[data-testid="stTextInput"],
            div[data-testid="stTextArea"],
            div[data-testid="stSelectbox"],
            div[data-testid="stDateInput"] {
                width: 100% !important;
                min-width: 0 !important;
            }
            div[data-testid="stNumberInput"] input,
            div[data-testid="stTextInput"] input,
            div[data-testid="stTextArea"] textarea {
                width: 100% !important;
                max-width: 100% !important;
                min-height: 2.75rem;
                box-sizing: border-box;
                font-size: 16px !important;
            }
            div[data-testid="stButton"],
            div[data-testid="stDownloadButton"],
            div[data-testid="stFormSubmitButton"] {
                width: 100% !important;
            }
            div[data-testid="stElementContainer"]:has(
                > div[data-testid="stButton"],
                > div[data-testid="stDownloadButton"],
                > div[data-testid="stFormSubmitButton"]
            ) {
                width: 100% !important;
            }
            div[data-testid="stButton"] button,
            div[data-testid="stDownloadButton"] button,
            div[data-testid="stFormSubmitButton"] button {
                width: 100% !important;
                min-height: 2.75rem;
                padding: 0.55rem 0.75rem;
                touch-action: manipulation;
            }
            div[data-testid="stRadio"] div[role="radiogroup"] {
                display: flex !important;
                flex-wrap: wrap !important;
                gap: 0.4rem !important;
                width: 100%;
            }
            div[data-testid="stRadio"] div[role="radiogroup"] > label {
                flex: 1 1 calc(33.333% - 0.4rem);
                min-width: 6.2rem;
                min-height: 2.75rem;
                margin: 0 !important;
                padding: 0.5rem 0.55rem;
                border: 1px solid #cbd5e1;
                border: 1px solid color-mix(
                    in srgb,
                    var(--text-color, #111827) 28%,
                    transparent
                );
                border-radius: 8px;
                background: var(--secondary-background-color, #f8fafc);
                color: var(--text-color, #111827) !important;
                align-items: center;
            }
            div[data-testid="stRadio"] div[role="radiogroup"] > label *,
            div[data-testid="stRadio"] div[role="radiogroup"] > label p,
            div[data-testid="stRadio"] div[role="radiogroup"] > label span {
                color: inherit !important;
                opacity: 1 !important;
            }
            div[data-testid="stRadio"] div[role="radiogroup"] > label:has(input:checked),
            div[data-testid="stRadio"] div[role="radiogroup"] > label:has(input[tabindex="0"]) {
                border-color: var(--primary-color, #2563eb);
                background: #dbeafe;
                background: color-mix(
                    in srgb,
                    var(--primary-color, #2563eb) 18%,
                    var(--background-color, #ffffff)
                );
                color: var(--text-color, #111827) !important;
                box-shadow: inset 0 0 0 1px var(--primary-color, #2563eb);
            }
            div[data-testid="stRadio"] div[role="radiogroup"] > label:has(input:disabled) {
                opacity: 0.82 !important;
            }
            div[data-testid="stRadio"] div[role="radiogroup"] > label p {
                white-space: normal !important;
                overflow-wrap: anywhere;
                line-height: 1.35 !important;
            }
            .st-key-profit_platform
            div[data-testid="stRadio"] div[role="radiogroup"] > label {
                flex: 1 1 calc(33.333% - 0.4rem);
            }
            .st-key-shipping_carrier_filter
            div[data-testid="stRadio"] div[role="radiogroup"] > label {
                flex: 1 1 calc(50% - 0.4rem);
            }
            .st-key-registration_shipping_result_id
            div[data-testid="stRadio"] div[role="radiogroup"] > label {
                flex: 1 1 100%;
                width: 100%;
                min-width: 100%;
                padding: 0.7rem 0.75rem;
                font-weight: 700;
            }
            div[data-testid="stButton"] button:not([kind="primary"]),
            div[data-testid="stDownloadButton"] button {
                color: var(--text-color, #111827) !important;
            }
            div[data-testid="stButton"] button *,
            div[data-testid="stDownloadButton"] button * {
                color: inherit !important;
            }
            div[class*="st-key-direct_register_"] button {
                width: 100% !important;
                min-height: 3rem !important;
                border-color: #1d4ed8 !important;
                background: #2563eb !important;
                color: #ffffff !important;
                font-weight: 800 !important;
                white-space: normal !important;
                line-height: 1.35 !important;
            }
            div[class*="st-key-direct_register_"] button * {
                color: #ffffff !important;
            }
            div[class*="st-key-direct_register_"] button:disabled {
                border-color: #64748b !important;
                background: #64748b !important;
                color: #ffffff !important;
                opacity: 0.72 !important;
            }
            .mobile-registration-selection {
                display: block;
                border: 1px solid #cbd5e1;
                border: 1px solid color-mix(
                    in srgb,
                    var(--text-color, #111827) 22%,
                    transparent
                );
                border-radius: 8px;
                background: var(--secondary-background-color, #f8fafc);
                color: var(--text-color, #111827);
                padding: 0.75rem;
                margin: 0.35rem 0 0.65rem;
            }
            .mobile-registration-selection-title {
                color: var(--text-color, #111827);
                font-size: 0.76rem;
                font-weight: 700;
                opacity: 0.78;
                margin-bottom: 0.25rem;
            }
            .mobile-registration-selection-service {
                color: var(--text-color, #111827);
                font-size: 0.92rem;
                font-weight: 800;
                line-height: 1.35;
                overflow-wrap: anywhere;
                margin-bottom: 0.45rem;
            }
            .mobile-registration-selection-grid {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 0.4rem;
            }
            .mobile-registration-selection-grid div {
                min-width: 0;
                border-radius: 7px;
                background: var(--background-color, #ffffff);
                color: var(--text-color, #111827);
                padding: 0.45rem 0.5rem;
            }
            .mobile-registration-selection-grid span {
                display: block;
                color: var(--text-color, #111827);
                font-size: 0.68rem;
                opacity: 0.72;
            }
            .mobile-registration-selection-grid strong {
                display: block;
                color: var(--text-color, #111827);
                font-size: 0.84rem;
                line-height: 1.3;
                overflow-wrap: anywhere;
            }
            div[data-testid="stAlert"],
            div[data-testid="stMarkdownContainer"],
            div[data-testid="stCaptionContainer"] {
                max-width: 100%;
                overflow-wrap: anywhere;
                word-break: break-word;
            }
            pre,
            code {
                max-width: 100%;
                white-space: pre-wrap !important;
                overflow-wrap: anywhere;
            }
            .summary-grid {
                grid-template-columns: 1fr;
            }
            .comparison-table,
            .comparison-table thead,
            .comparison-table tbody,
            .comparison-table tr,
            .comparison-table th,
            .comparison-table td {
                display: block;
                width: 100% !important;
            }
            .comparison-table {
                font-size: 0.82rem;
            }
            .comparison-table thead {
                display: none;
            }
            .comparison-table tr {
                border-bottom: 1px solid #e5e7eb;
                padding: 0.45rem 0.5rem;
            }
            .comparison-table td {
                border-bottom: 0;
                display: grid;
                grid-template-columns: 6.5rem 1fr;
                gap: 0.4rem;
                padding: 0.16rem 0;
            }
            .comparison-table td::before {
                content: attr(data-label);
                color: #64748b;
                font-weight: 700;
            }
            .detail-summary-grid,
            .detail-kv-grid,
            .simple-profit-grid {
                grid-template-columns: 1fr;
            }
            .simple-profit-card,
            .summary-card,
            .compact-section {
                width: 100%;
                max-width: 100%;
                padding: 0.7rem;
                box-sizing: border-box;
                overflow: hidden;
            }
            .simple-profit-value,
            .summary-mini-value,
            .detail-value {
                white-space: normal;
                overflow-wrap: anywhere;
            }
            .detail-section {
                padding: 0.7rem;
            }
            .breakdown-row {
                align-items: flex-start;
                flex-direction: column;
                gap: 0.12rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header() -> None:
    st.set_page_config(page_title="EBリサーチプラス利益計算ツール", layout="wide")
    inject_compact_css()
    st.title("EBリサーチプラス利益計算ツール")
    st.caption("販売プラットフォームに合わせて、必要な費用と利益を計算します。")


def render_exchange_rate() -> tuple[str, float, float]:
    """Render the selected currency rate and return product and USD rates."""
    st.markdown("### 為替レート")
    currency_col, rate_col, button_col, time_col = st.columns([0.9, 1.1, 0.9, 1.4])
    currency = currency_col.selectbox(
        "販売通貨",
        SUPPORTED_CURRENCIES,
        index=SUPPORTED_CURRENCIES.index(
            normalize_currency(st.session_state.get("exchange_currency"))
        ),
        format_func=currency_option_label,
        key="exchange_currency",
    )
    load_exchange_rate(currency)
    rate_col.number_input(
        f"現在の{currency}/JPYレート",
        min_value=0.01,
        step=0.0001,
        format="%.4f",
        key="exchange_rate_input",
        on_change=apply_manual_exchange_rate,
        args=(currency,),
    )
    button_col.button(
        "最新レートに更新",
        use_container_width=True,
        on_click=update_exchange_rate_from_api,
        kwargs={"trigger": "button", "currency_code": currency},
    )

    saved_data = read_shared_exchange_rate_data(currency) or {}
    time_col.caption(f"取得元: {saved_data.get('source', '保存済みレート')}")
    time_col.caption(
        "API更新日時: "
        f"{saved_data.get('api_updated_at') or saved_data.get('time_last_update_utc') or '不明'}"
    )
    time_col.caption(
        f"取得日時: {saved_data.get('fetched_at') or saved_data.get('updated_at') or '未取得'}"
    )

    if saved_data.get("mode") == "manual":
        api_rate = saved_data.get("api_rate")
        api_text = f"{float(api_rate):.4f}" if isinstance(api_rate, (int, float)) else "不明"
        st.info(f"手動設定中です。最後に取得したAPI自動取得値: {api_text}")

    message = st.session_state.get("exchange_rate_message")
    if message and message.get("currency_code") != currency:
        message = None
    if message:
        if message.get("type") == "error":
            st.error(
                "為替レートの取得に失敗したため、現在の保存済みレートを継続して使用します。\n\n"
                f"詳細: {message.get('error')}"
            )
        elif message.get("type") == "manual":
            st.info(
                f"{currency}/JPYを手動で{float(message.get('after')):.4f}円に設定しました。"
            )
        else:
            before = message.get("before")
            after = message.get("after")
            if message.get("fallback_used"):
                st.warning(
                    "メインAPIの取得に失敗したため、予備APIのレートを使用しています。"
                )
            if (
                message.get("api_updated_before")
                and message.get("api_updated_before") == message.get("api_updated_after")
            ):
                st.info(
                    "API側の為替データはまだ更新されていません。"
                    "現在のレートを継続して使用します。"
                )
            elif before is not None and before != after:
                st.success(
                    f"{currency}/JPYを{float(before):.4f}円から"
                    f"{float(after):.4f}円へ更新しました。"
                )
            else:
                st.success(
                    f"最新の{currency}/JPYレートを取得しました: "
                    f"{float(after):.4f}円"
                )

    with st.expander("為替レートの詳細情報", expanded=False):
        st.json(saved_data)
        st.caption(
            f"異常値判定: 前回値から{EXCHANGE_RATE_MAX_CHANGE_PERCENT:.1f}%超の変動、"
            f"またはAPI更新から{EXCHANGE_RATE_MAX_AGE_HOURS:.0f}時間超の場合は"
            "自動適用しません。"
        )
    selected_rate = float(st.session_state.exchange_rate)
    usd_jpy_rate = (
        selected_rate
        if currency == "USD"
        else read_shared_exchange_rate("USD") or DEFAULT_JPY_RATES["USD"]
    )
    return currency, selected_rate, float(usd_jpy_rate)


def render_inputs(
    exchange_rate: float,
    currency_code: str,
    usd_jpy_rate: float,
) -> ProductInputs:
    st.markdown("### 商品情報・販売条件")
    if st.button("手数料を初期値に戻す", help="eBay手数料率と広告率だけを初期値へ戻します。"):
        st.session_state.input_ebay_fee_rate = DEFAULT_EBAY_FEE_RATE
        st.session_state.input_ad_rate = DEFAULT_AD_RATE
        st.session_state.input_fixed_fee_usd = DEFAULT_FIXED_FEE_USD
        st.session_state.input_copy_cost_yen = DEFAULT_COPY_COST_YEN
        st.rerun()

    product_col1, product_col2, product_col3, product_col4 = st.columns([1.35, 0.75, 0.8, 0.8])
    product_name = product_col1.text_input("商品名")
    sku = product_col2.text_input("SKU")
    destination_country = product_col3.selectbox("配送先の国", DEFAULT_COUNTRIES)
    postal_code = product_col4.text_input("郵便番号", help="米国向けのOrange Connex / FedExゾーン判定に使用します。")

    price_col1, price_col2, price_col3 = st.columns(3)
    sale_price_usd = price_col1.number_input(
        f"販売価格（{currency_code} / {currency_symbol(currency_code)}）",
        min_value=0.0,
        value=DEFAULT_SALE_PRICE_FOREIGN,
        step=1.0,
        format="%.2f",
    )
    buyer_shipping_usd = 0.0
    purchase_price_yen = price_col2.number_input(
        "仕入れ価格（円）",
        min_value=0.0,
        value=0.0,
        step=100.0,
        format="%.0f",
    )
    weight_g = price_col3.number_input(
        "実重量（g）",
        min_value=0.0,
        value=0.0,
        step=10.0,
        format="%.0f",
    )

    size_col1, size_col2, size_col3 = st.columns(3)
    length_cm = size_col1.number_input("長さ（cm）", min_value=0.0, value=0.0, step=1.0, format="%.1f")
    width_cm = size_col2.number_input("幅（cm）", min_value=0.0, value=0.0, step=1.0, format="%.1f")
    height_cm = size_col3.number_input("高さ（cm）", min_value=0.0, value=0.0, step=1.0, format="%.1f")

    fee_col1, fee_col2, fee_col3, fee_col4 = st.columns(4)
    ebay_fee_rate = fee_col1.number_input("eBay手数料率", min_value=0.0, max_value=99.0, value=DEFAULT_EBAY_FEE_RATE, step=0.1, format="%.2f", key="input_ebay_fee_rate", help="カテゴリー手数料はこの率に含めて入力してください。")
    overseas_fee_rate = fee_col2.number_input("海外手数料率", min_value=0.0, max_value=99.0, value=DEFAULT_OVERSEAS_FEE_RATE, step=0.1, format="%.2f")
    ad_rate = fee_col3.number_input("広告率", min_value=0.0, max_value=99.0, value=DEFAULT_AD_RATE, step=0.1, format="%.2f", key="input_ad_rate")
    other_fee_yen = fee_col4.number_input("その他手数料", min_value=0.0, value=0.0, step=100.0, format="%.0f")

    with st.expander("詳細設定（国内費用・固定手数料）", expanded=False):
        detail_col1, detail_col2, detail_col3, detail_col4 = st.columns(4)
        domestic_shipping_yen = detail_col1.number_input(
            "コピー代（円）",
            min_value=0.0,
            value=DEFAULT_COPY_COST_YEN,
            step=100.0,
            format="%.0f",
            help="商品のコピー、印刷、資料作成などにかかる費用を入力してください。",
            key="input_copy_cost_yen",
        )
        packaging_yen = detail_col2.number_input("梱包資材費（円）", min_value=0.0, value=0.0, step=50.0, format="%.0f")
        fixed_fee_usd = detail_col3.number_input("固定手数料（USD）", min_value=0.0, value=DEFAULT_FIXED_FEE_USD, step=0.1, format="%.2f", key="input_fixed_fee_usd")
        target_profit_yen = detail_col4.number_input("目標利益（円）", min_value=0.0, value=0.0, step=100.0, format="%.0f")
        st.caption("カテゴリー手数料は、上の eBay手数料率 に含めて入力してください。")

    with st.expander("URLなど登録用の補足情報", expanded=False):
        url_col1, url_col2 = st.columns(2)
        source_url = url_col1.text_input("仕入れ先URL")
        product_url = url_col2.text_input("商品URL")
        memo = st.text_area(
            "メモ",
            height=80,
            help="出品管理ツールへ登録する補足情報です。",
        )

    return ProductInputs(
        product_name=product_name,
        sku=sku,
        sale_price_usd=sale_price_usd,
        buyer_shipping_usd=buyer_shipping_usd,
        purchase_price_yen=purchase_price_yen,
        domestic_shipping_yen=domestic_shipping_yen,
        packaging_yen=packaging_yen,
        destination_country=destination_country,
        weight_g=weight_g,
        length_cm=length_cm,
        width_cm=width_cm,
        height_cm=height_cm,
        ebay_fee_rate=ebay_fee_rate,
        overseas_fee_rate=overseas_fee_rate,
        ad_rate=ad_rate,
        other_fee_yen=other_fee_yen,
        fixed_fee_usd=fixed_fee_usd,
        target_profit_yen=target_profit_yen,
        product_url=product_url,
        source_url=source_url,
        exchange_rate=exchange_rate,
        postal_code=postal_code,
        memo=memo,
        currency_code=currency_code,
        usd_jpy_rate=usd_jpy_rate,
    )


def render_platform_selector() -> str:
    return st.radio(
        "販売プラットフォーム",
        PLATFORM_OPTIONS,
        index=0,
        horizontal=True,
        key="profit_platform",
        help="選択した販売先に必要な入力項目と利益計算へ切り替わります。",
    )


def normalize_yen_text_input(key: str) -> None:
    raw = str(st.session_state.get(key, "")).replace(",", "").strip()
    try:
        value = max(0.0, float(raw or 0))
    except ValueError:
        return
    st.session_state[key] = f"{value:,.0f}"


def yen_text_input(
    container: Any,
    label: str,
    *,
    key: str,
    value: float = 0.0,
) -> float:
    if key not in st.session_state:
        st.session_state[key] = f"{value:,.0f}"
    raw = container.text_input(
        label,
        key=key,
        on_change=normalize_yen_text_input,
        args=(key,),
    )
    try:
        parsed = float(str(raw).replace(",", "").strip() or 0)
    except ValueError:
        container.error("金額は数字で入力してください。")
        return 0.0
    if parsed < 0:
        container.error("金額は0円以上で入力してください。")
        return 0.0
    return parsed


def render_simple_profit_summary(
    inputs: SimpleProfitInputs,
    result: SimpleProfitCalculation,
) -> None:
    profit_class = "positive" if result.profit_yen >= 0 else "negative"
    price_label = (
        "売却価格"
        if inputs.platform == PLATFORM_IPHONE_RESALE
        else "販売価格"
    )
    summary_items = [
        (
            "<div>"
            f'<div class="simple-profit-label">{price_label}</div>'
            f'<div class="simple-profit-value">{yen(inputs.sale_price_yen)}</div>'
            "</div>"
        )
    ]
    if inputs.platform != PLATFORM_IPHONE_RESALE:
        summary_items.append(
            "<div>"
            '<div class="simple-profit-label">販売手数料</div>'
            f'<div class="simple-profit-value">{yen(result.sales_fee_yen)}</div>'
            "</div>"
        )
    summary_items.extend(
        [
            (
                "<div>"
                '<div class="simple-profit-label">利益</div>'
                f'<div class="simple-profit-value {profit_class}">'
                f"{yen(result.profit_yen)}</div>"
                "</div>"
            ),
            (
                "<div>"
                '<div class="simple-profit-label">利益率</div>'
                f'<div class="simple-profit-value {profit_class}">'
                f"{result.profit_margin:.1f}%</div>"
                "</div>"
            ),
        ]
    )
    summary_html = (
        '<div class="simple-profit-card">'
        '<div class="simple-profit-grid">'
        + "".join(summary_items)
        + "</div></div>"
    )
    st.markdown(
        summary_html,
        unsafe_allow_html=True,
    )
    if result.profit_yen < 0:
        st.error(f"赤字です。予定損失は {yen(abs(result.profit_yen))} です。")


def render_simple_profit_calculator(platform: str) -> None:
    st.markdown(f"### {platform} 利益計算")
    key_prefix = "mercari" if platform == PLATFORM_MERCARI else "iphone"

    product_name = st.text_input(
        "商品名",
        key=f"{key_prefix}_product_name",
    )
    iphone_model = ""
    iphone_capacity = ""
    if platform == PLATFORM_IPHONE_RESALE:
        model_col, capacity_col = st.columns(2)
        iphone_model = model_col.text_input(
            "売却した業者",
            placeholder="例: イオシス、にこスマ、ゲオ",
            key="iphone_model",
        )
        iphone_capacity = capacity_col.text_input(
            "容量",
            placeholder="例: 256GB",
            key="iphone_capacity",
        )

    price_col, purchase_col = st.columns(2)
    sale_price_yen = yen_text_input(
        price_col,
        "売却価格（円）" if platform == PLATFORM_IPHONE_RESALE else "販売価格（円）",
        key=f"{key_prefix}_sale_price_yen",
    )
    purchase_price_yen = yen_text_input(
        purchase_col,
        "仕入れ価格（円）",
        key=f"{key_prefix}_purchase_price_yen",
    )

    fee_input_mode = FEE_MODE_AMOUNT
    fee_rate_percent = 0.0
    fee_amount_yen = 0.0
    other_cost_yen = 0.0
    if platform == PLATFORM_IPHONE_RESALE:
        shipping_yen = yen_text_input(
            st,
            "送料（円）",
            key=f"{key_prefix}_shipping_yen",
        )
    else:
        fee_mode_label = st.radio(
            "販売手数料の入力方法",
            ("料率（%）", "金額（円）"),
            horizontal=True,
            key=f"{key_prefix}_fee_mode_label",
        )
        fee_input_mode = (
            FEE_MODE_RATE if fee_mode_label == "料率（%）" else FEE_MODE_AMOUNT
        )
        fee_col, shipping_col, other_col = st.columns(3)
        if fee_input_mode == FEE_MODE_RATE:
            fee_rate_percent = fee_col.number_input(
                "販売手数料率（%）",
                min_value=0.0,
                max_value=100.0,
                value=0.0,
                step=0.1,
                format="%.2f",
                key=f"{key_prefix}_fee_rate_percent",
            )
        else:
            fee_amount_yen = yen_text_input(
                fee_col,
                "販売手数料（円）",
                key=f"{key_prefix}_fee_amount_yen",
            )
        shipping_yen = yen_text_input(
            shipping_col,
            "送料（円）",
            key=f"{key_prefix}_shipping_yen",
        )
        other_cost_yen = yen_text_input(
            other_col,
            "その他経費（円）",
            key=f"{key_prefix}_other_cost_yen",
        )

    repair_cost_yen = 0.0
    parts_cost_yen = 0.0

    memo = st.text_area(
        "メモ",
        height=90,
        key=f"{key_prefix}_memo",
    )
    inputs = SimpleProfitInputs(
        platform=platform,
        product_name=product_name,
        iphone_model=iphone_model,
        iphone_capacity=iphone_capacity,
        sale_price_yen=sale_price_yen,
        purchase_price_yen=purchase_price_yen,
        fee_input_mode=fee_input_mode,
        fee_rate_percent=fee_rate_percent,
        fee_amount_yen=fee_amount_yen,
        shipping_yen=shipping_yen,
        repair_cost_yen=repair_cost_yen,
        parts_cost_yen=parts_cost_yen,
        other_cost_yen=other_cost_yen,
        memo=memo,
    )
    result = calculate_simple_profit(
        platform=inputs.platform,
        sale_price_yen=inputs.sale_price_yen,
        purchase_price_yen=inputs.purchase_price_yen,
        fee_mode=inputs.fee_input_mode,
        fee_rate_percent=inputs.fee_rate_percent,
        fee_amount_yen=inputs.fee_amount_yen,
        shipping_yen=inputs.shipping_yen,
        other_cost_yen=inputs.other_cost_yen,
        repair_cost_yen=inputs.repair_cost_yen,
        parts_cost_yen=inputs.parts_cost_yen,
    )
    render_simple_profit_summary(inputs, result)

    if st.button(
        "出品管理ツールへ登録",
        type="primary",
        use_container_width=True,
        key=f"register_{key_prefix}",
    ):
        missing: list[str] = []
        if not inputs.product_name.strip():
            missing.append("商品名")
        if inputs.sale_price_yen <= 0:
            missing.append(
                "売却価格"
                if platform == PLATFORM_IPHONE_RESALE
                else "販売価格"
            )
        if missing:
            st.error("登録に必要な項目が不足しています: " + "、".join(missing))
            return
        outcome = register_simple_listing(inputs, result)
        if outcome.success:
            st.success(
                f"{platform}の商品を出品管理ツールへ登録しました。"
                f"保存ID: {outcome.listing_id} / 保存後の総件数: {outcome.total_count}件"
            )
            st.info(
                f"登録内容: {outcome.product_name} / 利益 {yen(result.profit_yen)}\n\n"
                f"保存先: `{outcome.database_path}`"
            )
            if outcome.notification_error:
                st.warning(
                    "データは保存されましたが、一覧の自動更新通知を作成できませんでした。"
                    f"詳細: {outcome.notification_error}"
                )
        else:
            st.error(
                "出品管理ツールへの登録に失敗しました。\n\n"
                f"保存先: `{outcome.database_path}`\n\n"
                f"詳細: {outcome.error}"
            )
    st.markdown('<div class="bottom-spacer"></div>', unsafe_allow_html=True)


def render_summary(results: list[ShippingResult]) -> None:
    available = [result for result in results if result.shippable and result.profit_yen is not None]
    st.markdown("### おすすめ配送方法")
    if not available:
        st.warning("発送可能な配送方法がありません。重量・サイズ・配送先、または料金表を確認してください。")
        return

    recommended = max(available, key=lambda item: item.profit_yen or 0)
    card_html = f"""
    <div class="summary-card">
      <div class="summary-title">おすすめ配送方法</div>
      <div class="summary-service">{html.escape(recommended.carrier)} / {html.escape(recommended.service)}</div>
      <div class="summary-grid">
        <div class="summary-mini">
          <div class="summary-mini-label">送料</div>
          <div class="summary-mini-value">{compact_yen(recommended.total_shipping_yen)}</div>
        </div>
        <div class="summary-mini">
          <div class="summary-mini-label">利益</div>
          <div class="summary-mini-value">{compact_yen(recommended.profit_yen)}</div>
        </div>
        <div class="summary-mini">
          <div class="summary-mini-label">利益率</div>
          <div class="summary-mini-value">{percent(recommended.profit_margin)}</div>
        </div>
        <div class="summary-mini">
          <div class="summary-mini-label">計算区分</div>
          <div class="summary-mini-value">{html.escape(recommended.calculation_mode)}</div>
        </div>
      </div>
      <div class="summary-note">{html.escape(recommended.note)}</div>
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)


def render_shipping_results(inputs: ProductInputs, results: list[ShippingResult]) -> list[ShippingResult]:
    st.markdown("### 配送方法別 送料・利益比較")
    filter_label = st.radio(
        "配送会社を選択",
        carrier_filter_options(),
        horizontal=True,
        key="shipping_carrier_filter",
    )
    sort_key = st.selectbox(
        "並び替え",
        ("利益が高い順", "送料が安い順", "利益率が高い順", "配送会社順"),
        key="shipping_sort_key",
    )
    sorted_results = sort_results(results, sort_key)

    selected_carrier = carrier_filter_value(filter_label)
    if selected_carrier is None:
        carrier_order = ["日本郵便", "SpeedPAK / CPaSS", "FedEx", "DHL"]
        for carrier in carrier_order:
            group_results = [result for result in sorted_results if result.carrier == carrier]
            if group_results:
                render_result_group(inputs, carrier if carrier != "SpeedPAK / CPaSS" else "SpeedPAK／CPaSS", group_results)
    else:
        filtered_results = [result for result in sorted_results if result.carrier == selected_carrier]
        render_result_group(inputs, filter_label, filtered_results)

    st.download_button(
        "配送比較結果をCSVでダウンロード",
        results_csv(sorted_results).encode("utf-8-sig"),
        file_name="shipping_profit_comparison.csv",
        mime="text/csv",
        disabled=not sorted_results,
    )
    return sorted_results


def render_registration(
    inputs: ProductInputs,
    results: list[ShippingResult],
) -> None:
    st.markdown("### 出品管理ツールへ登録")
    available = [result for result in results if result.shippable and result.profit_yen is not None]
    if not available:
        st.info("登録できる配送方法がありません。発送可能で料金登録済みの配送方法が必要です。")
        return

    recommended = max(available, key=lambda item: item.profit_yen or 0)
    options = [result.result_id for result in available]
    option_map = {result.result_id: result for result in available}
    preferred_id = st.session_state.get("selected_shipping_result_id")
    if preferred_id not in option_map:
        preferred_id = recommended.result_id
        st.session_state.selected_shipping_result_id = preferred_id
    registration_widget_key = "registration_shipping_result_id"
    if st.session_state.get(registration_widget_key) not in option_map:
        st.session_state.pop(registration_widget_key, None)
    selected_id = st.radio(
        "登録する配送方法",
        options,
        index=options.index(preferred_id),
        format_func=lambda result_id: (
            f"{option_map[result_id].carrier} / {option_map[result_id].service} "
            f"送料 {yen(option_map[result_id].total_shipping_yen)} "
            f"利益 {yen(option_map[result_id].profit_yen)} "
            f"利益率 {percent(option_map[result_id].profit_margin)} "
            f"区分 {option_map[result_id].calculation_mode}"
        ),
        key=registration_widget_key,
    )
    st.session_state.selected_shipping_result_id = selected_id
    selected_result = option_map.get(selected_id)
    if selected_result is not None:
        st.markdown(
            f"""
            <div class="mobile-registration-selection">
              <div class="mobile-registration-selection-title">選択中の配送方法</div>
              <div class="mobile-registration-selection-service">
                {html.escape(selected_result.carrier)} /
                {html.escape(selected_result.service)}
              </div>
              <div class="mobile-registration-selection-grid">
                <div><span>送料</span><strong>{compact_yen(selected_result.total_shipping_yen)}</strong></div>
                <div><span>利益</span><strong>{compact_yen(selected_result.profit_yen)}</strong></div>
                <div><span>利益率</span><strong>{percent(selected_result.profit_margin)}</strong></div>
                <div><span>計算区分</span><strong>{html.escape(selected_result.calculation_mode)}</strong></div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if st.button("出品管理へ登録", type="primary", use_container_width=True):
        submit_listing_registration(
            inputs,
            selected_result,
            source="bottom",
        )
    st.markdown('<div class="bottom-spacer"></div>', unsafe_allow_html=True)


def render_rate_book_info() -> None:
    with st.expander("送料データの管理"):
        st.write(f"料金表ファイル: `{SHIPPING_RATE_PATH}`")
        st.write("送料改定時は、このJSONの料金表を更新してください。プログラム本体の変更は不要です。")
        rate_book = load_shipping_rate_book()
        st.write(f"登録サービス数: {len(rate_book.get('services', []))}")
        metadata = rate_book.get("metadata")
        if isinstance(metadata, dict):
            st.write("PDF抽出メタ情報")
            st.json(metadata)


def render_zonos_settings() -> None:
    with st.expander("Zonos Prepay設定"):
        config = load_zonos_config()
        enabled = st.checkbox("有効", value=bool(config.get("enabled", True)), key="zonos_enabled")
        duty = dict(config.get("duty") or {})
        fee = dict(config.get("fee") or {})
        col1, col2, col3 = st.columns(3)
        duty_rate = col1.number_input("関税率(%)", min_value=0.0, max_value=99.0, value=float(duty.get("rate_percent", 10.0)), step=0.1, format="%.2f")
        duty_base = col2.selectbox(
            "関税対象",
            ("product_price_yen", "product_price_yen_plus_shipping"),
            index=0 if str(duty.get("base", "product_price_yen")) == "product_price_yen" else 1,
        )
        fee_base = col3.selectbox(
            "Zonos手数料基準",
            ("product_price_yen_plus_shipping", "product_price_yen"),
            index=0 if str(fee.get("base", "product_price_yen_plus_shipping")) == "product_price_yen_plus_shipping" else 1,
        )
        date_col1, date_col2 = st.columns(2)
        effective_from = date_col1.text_input("適用開始日", value=str(duty.get("effective_from") or fee.get("effective_from") or ""))
        effective_to = date_col2.text_input("適用終了日", value=str(duty.get("effective_to") or fee.get("effective_to") or ""))
        points_text = st.text_area(
            "Zonos手数料率の基準点(JSON)",
            value=json.dumps(fee.get("points", []), ensure_ascii=False, indent=2),
            height=220,
        )
        st.caption("20,000円超は現在登録されている最終手数料率を使用します。")
        if st.button("Zonos設定を保存"):
            try:
                points = json.loads(points_text)
                if not isinstance(points, list):
                    raise ValueError("基準点JSONは配列にしてください。")
                config["enabled"] = enabled
                config["duty"] = {
                    **duty,
                    "rate_percent": duty_rate,
                    "base": duty_base,
                    "effective_from": effective_from,
                    "effective_to": effective_to,
                }
                config["fee"] = {
                    **fee,
                    "base": fee_base,
                    "rounding": str(fee.get("rounding") or "half_up"),
                    "above_max": str(fee.get("above_max") or "use_last_rate"),
                    "effective_from": effective_from,
                    "effective_to": effective_to,
                    "points": points,
                }
                save_zonos_config(config)
                st.success("Zonos設定を保存しました。")
            except (json.JSONDecodeError, ValueError) as exc:
                st.error(f"Zonos設定を保存できませんでした: {exc}")


def main() -> None:
    render_header()
    platform = render_platform_selector()
    if platform != PLATFORM_EBAY:
        render_simple_profit_calculator(platform)
        return

    currency_code, exchange_rate, usd_jpy_rate = render_exchange_rate()
    inputs = render_inputs(exchange_rate, currency_code, usd_jpy_rate)
    results = calculate_shipping_results(inputs)
    st.divider()
    render_summary(results)
    sorted_results = render_shipping_results(inputs, results)
    st.divider()
    render_registration(inputs, sorted_results)
    render_rate_book_info()
    render_zonos_settings()


if __name__ == "__main__":
    main()
