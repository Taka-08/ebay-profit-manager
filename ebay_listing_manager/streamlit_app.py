from __future__ import annotations

import html
import csv
import io
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_paths import (  # noqa: E402
    resolve_exchange_rate_path,
    resolve_listing_db_path,
    resolve_registration_event_path,
)
from app_auth import require_app_password  # noqa: E402
from app_database import (  # noqa: E402
    database_location_label,
    get_database_connection,
    remote_database_is_configured,
)
from currency_config import (  # noqa: E402
    DEFAULT_CURRENCY,
    DEFAULT_JPY_RATES,
    SUPPORTED_CURRENCIES,
    currency_option_label,
    currency_symbol,
    normalize_currency,
)
from platform_config import (  # noqa: E402
    FEE_MODE_AMOUNT,
    FEE_MODE_RATE,
    PLATFORM_EBAY,
    PLATFORM_IPHONE_RESALE,
    PLATFORM_MERCARI,
    PLATFORM_OPTIONS,
    calculate_simple_profit,
    is_simple_platform,
    normalize_platform,
)


DB_PATH = resolve_listing_db_path(__file__)
SHARED_EXCHANGE_RATE_PATH = resolve_exchange_rate_path(__file__)
REGISTRATION_EVENT_PATH = resolve_registration_event_path(__file__)
STATUS_ACTIVE = "\u51fa\u54c1\u4e2d"
STATUS_SOLD = "\u58f2\u5374\u6e08"
STATUS_CANCELLED = "\u30ad\u30e3\u30f3\u30bb\u30eb"
ACTUAL_FEE_SCHEMA_LEGACY = 1
ACTUAL_FEE_SCHEMA_SEPARATE = 2
STATUS_OPTIONS = (STATUS_ACTIVE, STATUS_SOLD, STATUS_CANCELLED)
SUMMARY_SECTIONS = {
    STATUS_ACTIVE: "active",
    STATUS_SOLD: "sold",
    STATUS_CANCELLED: "cancelled",
}
SUMMARY_SECTION_STATUSES = {value: key for key, value in SUMMARY_SECTIONS.items()}
PLATFORM_ALL = "\u5168\u30d7\u30e9\u30c3\u30c8\u30d5\u30a9\u30fc\u30e0"
SHIPPING_CARRIER_OPTIONS = (
    "",
    "日本郵便",
    "SpeedPAK Economy",
    "FedEx",
    "DHL",
    "UPS",
    "ヤマト運輸",
    "佐川急便",
    "その他",
)


TEXT = {
    "app_title": "\u51fa\u54c1\u7ba1\u7406\u30c4\u30fc\u30eb",
    "caption": "\u5229\u76ca\u8a08\u7b97\u30c4\u30fc\u30eb\u304b\u3089\u767b\u9332\u3057\u305f\u8ca9\u8def\u5225\u30c7\u30fc\u30bf\u3092\u95b2\u89a7\u30fb\u7ba1\u7406\u3057\u307e\u3059\u3002",
    "dashboard": "\u30c0\u30c3\u30b7\u30e5\u30dc\u30fc\u30c9",
    "active_count": "\u51fa\u54c1\u4e2d\u4ef6\u6570",
    "sold_count": "\u58f2\u5374\u6e08\u4ef6\u6570",
    "cancelled_count": "\u30ad\u30e3\u30f3\u30bb\u30eb\u6e08\u307f\u4ef6\u6570",
    "registered_count": "\u767b\u9332\u6e08\u307f\u5546\u54c1\u6570",
    "monthly_profit": "\u4eca\u6708\u5229\u76ca",
    "total_profit": "\u7d2f\u8a08\u5229\u76ca",
    "listing_management": "\u767b\u9332\u6e08\u307f\u51fa\u54c1\u4e00\u89a7\u30fb\u30b9\u30c6\u30fc\u30bf\u30b9\u7ba1\u7406",
    "product_name": "\u5546\u54c1\u540d",
    "platform": "\u8ca9\u58f2\u30d7\u30e9\u30c3\u30c8\u30d5\u30a9\u30fc\u30e0",
    "listing_date": "\u51fa\u54c1\u65e5",
    "currency_code": "販売通貨",
    "sale_price_usd": "販売価格（商品通貨）",
    "buyer_shipping_usd": "購入者から受け取る送料（商品通貨）",
    "exchange_rate": "予定為替レート（商品通貨/JPY）",
    "usd_jpy_rate": "予定USD/JPYレート",
    "purchase_price_yen": "\u4ed5\u5165\u4fa1\u683c\uff08\u5186\uff09",
    "domestic_shipping_yen": "\u30b3\u30d4\u30fc\u4ee3\uff08\u5186\uff09",
    "international_shipping_yen": "\u6d77\u5916\u9001\u6599\uff08\u5186\uff09",
    "packaging_yen": "\u68b1\u5305\u8cc7\u6750\u8cbb\uff08\u5186\uff09",
    "other_cost_yen": "\u305d\u306e\u4ed6\u30b3\u30b9\u30c8\uff08\u5186\uff09",
    "ebay_fee_rate": "eBay\u624b\u6570\u6599\u7387\uff08%\uff09",
    "promoted_listing_rate": "\u5e83\u544a\u7387\uff08%\uff09",
    "exchange_spread_rate": "\u70ba\u66ff\u5dee\u640d\u30fb\u6c7a\u6e08\u30b3\u30b9\u30c8\uff08%\uff09",
    "fixed_fee_usd": "\u56fa\u5b9a\u624b\u6570\u6599\uff08USD\uff09",
    "target_profit_yen": "\u76ee\u6a19\u5229\u76ca\uff08\u5186\uff09",
    "profit_yen": "\u5229\u76ca\uff08\u5186\uff09",
    "profit_margin": "\u5229\u76ca\u7387\uff08%\uff09",
    "roi": "ROI\uff08%\uff09",
    "gross_sales_yen": "\u5186\u63db\u7b97\u58f2\u4e0a",
    "break_even_sale_price_usd": "\u640d\u76ca\u5206\u5c90\u4fa1\u683c\uff08USD\uff09",
    "target_sale_price_usd": "\u76ee\u6a19\u5229\u76ca\u9054\u6210\u4fa1\u683c\uff08USD\uff09",
    "calculated_at": "\u8a08\u7b97\u65e5\u6642",
    "status": "\u30b9\u30c6\u30fc\u30bf\u30b9",
    "actual_sale_price_usd": "実際の販売価格（商品通貨）",
    "actual_buyer_shipping_usd": "購入者から受け取った送料（商品通貨）",
    "actual_ebay_fee_usd": "eBay\u53d6\u5f15\u624b\u6570\u6599\uff08USD\uff09",
    "actual_ad_fee_usd": "\u4e00\u822c\u5e83\u544a\u6599 / Promoted Listings\u5e83\u544a\u6599\uff08USD\uff09",
    "actual_fixed_fee_usd": "\u56fa\u5b9a\u624b\u6570\u6599\uff08USD\uff09",
    "actual_exchange_rate": "実績為替レート（商品通貨/JPY）",
    "actual_usd_jpy_rate": "手数料換算用USD/JPY実績レート",
    "actual_order_revenue_yen": "注文の収益（円）",
    "actual_purchase_price_yen": "\u5b9f\u969b\u306e\u4ed5\u5165\u4fa1\u683c\uff08\u5186\uff09",
    "actual_overseas_fee_yen": "\u5b9f\u969b\u306e\u6d77\u5916\u624b\u6570\u6599\u30fb\u6c7a\u6e08\u30b3\u30b9\u30c8\uff08\u5186\uff09",
    "actual_copy_cost_yen": "\u5b9f\u969b\u306e\u30b3\u30d4\u30fc\u4ee3\uff08\u5186\uff09",
    "actual_packaging_yen": "\u5b9f\u969b\u306e\u68b1\u5305\u8cc7\u6750\u8cbb\uff08\u5186\uff09",
    "actual_other_cost_yen": "\u5b9f\u969b\u306e\u305d\u306e\u4ed6\u30b3\u30b9\u30c8\uff08\u5186\uff09",
    "actual_base_shipping_yen": "\u5b9f\u969b\u306e\u57fa\u672c\u9001\u6599\uff08\u5186\uff09",
    "actual_fuel_surcharge_yen": "\u5b9f\u969b\u306e\u71c3\u6cb9\u30b5\u30fc\u30c1\u30e3\u30fc\u30b8\uff08\u5186\uff09",
    "actual_zonos_fee_yen": "\u5b9f\u969b\u306eZonos\u624b\u6570\u6599\uff08\u5186\uff09",
    "actual_duty_yen": "\u5b9f\u969b\u306e\u95a2\u7a0e\uff08\u5186\uff09",
    "actual_additional_fee_yen": "\u5b9f\u969b\u306e\u305d\u306e\u4ed6\u8ffd\u52a0\u6599\u91d1\uff08\u5186\uff09",
    "effective_ebay_fee_rate": "\u5b9f\u8ceaeBay\u624b\u6570\u6599\u7387\uff08%\uff09",
    "effective_ad_fee_rate": "\u5b9f\u8cea\u5e83\u544a\u8cbb\u7387\uff08%\uff09",
    "actual_shipping_yen": "\u5b9f\u969b\u306e\u9001\u6599\uff08\u5186\uff09",
    "shipping_carrier": "発送業者",
    "shipping_service": "実績配送サービス",
    "shipping_weight_g": "発送重量(g)",
    "actual_profit_yen": "\u5b9f\u5229\u76ca\uff08\u5186\uff09",
    "actual_profit_margin": "実績利益率（%）",
    "actual_profit_save": "\u4fdd\u5b58\u3059\u308b\u5b9f\u5229\u76ca\uff08\u5186\uff09",
    "actual_profit_auto": "\u81ea\u52d5\u8a08\u7b97\u306e\u5b9f\u5229\u76ca",
    "sold_date": "\u58f2\u5374\u65e5",
    "update": "\u66f4\u65b0",
    "delete": "\u524a\u9664",
    "updated": "\u30b9\u30c6\u30fc\u30bf\u30b9\u3068\u58f2\u5374\u5f8c\u60c5\u5831\u3092\u66f4\u65b0\u3057\u307e\u3057\u305f\u3002",
    "deleted": "\u51fa\u54c1\u60c5\u5831\u3092\u524a\u9664\u3057\u307e\u3057\u305f\u3002",
    "empty": "\u307e\u3060\u51fa\u54c1\u60c5\u5831\u306f\u3042\u308a\u307e\u305b\u3093\u3002",
    "select_listing": "\u7ba1\u7406\u3059\u308b\u51fa\u54c1",
    "database_file": "\u4fdd\u5b58\u5148DB",
    "refresh": "\u6700\u65b0\u306e\u72b6\u614b\u306b\u66f4\u65b0",
    "saved_data": "\u4fdd\u5b58\u30c7\u30fc\u30bf",
    "search": "\u7ba1\u7406\u3059\u308b\u51fa\u54c1\u3092\u691c\u7d22\uff08\u5546\u54c1\u540d\uff09",
    "search_placeholder": "\u4f8b: \u30ab\u30e1\u30e9",
    "platform_filter": "\u8ca9\u58f2\u30d7\u30e9\u30c3\u30c8\u30d5\u30a9\u30fc\u30e0\u3067\u7d5e\u308a\u8fbc\u307f",
    "status_filter": "\u30b9\u30c6\u30fc\u30bf\u30b9\u3067\u7d5e\u308a\u8fbc\u307f",
    "all_statuses": "\u3059\u3079\u3066",
    "no_management_results": "\u6761\u4ef6\u306b\u5408\u3046\u7ba1\u7406\u5bfe\u8c61\u306e\u51fa\u54c1\u304c\u3042\u308a\u307e\u305b\u3093\u3002",
    "summary_list": "\u8981\u70b9\u4e00\u89a7",
    "full_list": "\u5168\u4f53\u9805\u76ee",
    "platform_profit": "\u8ca9\u8def\u5225\u5229\u76ca",
    "duplicate": "\u8907\u88fd",
    "duplicated": "\u51fa\u54c1\u30c7\u30fc\u30bf\u3092\u8907\u88fd\u3057\u307e\u3057\u305f\u3002",
    "edit_listing": "\u51fa\u54c1\u30c7\u30fc\u30bf\u3092\u7de8\u96c6",
    "save_listing_edits": "\u51fa\u54c1\u30c7\u30fc\u30bf\u3092\u4fdd\u5b58",
    "listing_saved": "\u51fa\u54c1\u30c7\u30fc\u30bf\u3092\u4fdd\u5b58\u3057\u307e\u3057\u305f\u3002",
    "click_product_to_edit": "\u8981\u70b9\u4e00\u89a7\u306e\u5546\u54c1\u540d\u3092\u30af\u30ea\u30c3\u30af\u3059\u308b\u3068\u3001\u4e0b\u306e\u7ba1\u7406\u3059\u308b\u51fa\u54c1\u3067\u7de8\u96c6\u3067\u304d\u307e\u3059\u3002",
    "search_keyword": "\u691c\u7d22\u30ad\u30fc\u30ef\u30fc\u30c9",
    "monthly_sales": "\u58f2\u308c\u305f\u500b\u6570\uff08\u6708\u9593\u8ca9\u58f2\u6570\uff09",
    "competitor_count": "\u30e9\u30a4\u30d0\u30eb\u51fa\u54c1\u6570",
    "product_url": "\u5546\u54c1URL",
    "research_shipping_weight_g": "\u30ea\u30b5\u30fc\u30c1\u767a\u9001\u91cd\u91cf(g)",
    "inventory_risk": "\u5728\u5eab\u30ea\u30b9\u30af",
    "research_memo": "\u30ea\u30b5\u30fc\u30c1\u30e1\u30e2",
    "sku": "SKU",
    "source_url": "\u4ed5\u5165\u308c\u5148URL",
    "destination_country": "\u914d\u9001\u5148\u56fd",
    "sale_price_yen": "\u8ca9\u58f2\u4fa1\u683c\u306e\u5186\u63db\u7b97\u984d",
    "package_weight_g": "\u91cd\u91cf(g)",
    "package_length_cm": "\u9577\u3055(cm)",
    "package_width_cm": "\u5e45(cm)",
    "package_height_cm": "\u9ad8\u3055(cm)",
    "expected_shipping_carrier": "\u4e88\u5b9a\u914d\u9001\u4f1a\u793e",
    "expected_shipping_service": "\u4e88\u5b9a\u914d\u9001\u30b5\u30fc\u30d3\u30b9",
    "planned_shipping_yen": "\u4e88\u5b9a\u9001\u6599",
    "planned_profit_margin": "\u4e88\u5b9a\u5229\u76ca\u7387",
    "planned_base_shipping_yen": "基本送料",
    "planned_fuel_surcharge_yen": "燃油サーチャージ",
    "planned_additional_fee_yen": "追加料金",
    "planned_shipping_status": "発送可否",
    "planned_shipping_reason": "発送不可理由",
    "rate_table_weight_g": "料金重量(g)",
    "shipping_breakdown_json": "送料内訳",
    "overseas_fee_rate": "\u6d77\u5916\u624b\u6570\u6599\u7387(%)",
    "overseas_fee_yen": "\u6d77\u5916\u624b\u6570\u6599",
    "other_fee_yen": "\u305d\u306e\u4ed6\u624b\u6570\u6599",
    "shipping_calculation_mode": "\u8a08\u7b97\u533a\u5206",
    "volumetric_weight_g": "\u5bb9\u7a4d\u91cd\u91cf(g)",
    "applied_weight_g": "\u9069\u7528\u91cd\u91cf(g)",
    "billing_weight_g": "\u8acb\u6c42\u91cd\u91cf(g)",
    "zonos_applied": "Zonos適用",
    "zonos_base_shipping_yen": "日本郵便基本送料",
    "zonos_fee_base_yen": "Zonos手数料基準額",
    "zonos_fee_rate_percent": "Zonos手数料率",
    "zonos_fee_yen": "Zonos手数料",
    "zonos_duty_rate_percent": "関税率",
    "zonos_duty_base_yen": "関税対象額",
    "zonos_duty_yen": "関税額",
    "zonos_total_shipping_yen": "Zonos込み配送関連費用",
    "zonos_config_effective_from": "Zonos設定発効日",
    "zonos_config_effective_to": "Zonos設定終了日",
    "registered_at": "\u767b\u9332\u65e5\u6642",
    "sales_fee_input_mode": "販売手数料の入力方法",
    "sales_fee_rate": "販売手数料率（%）",
    "sales_fee_yen": "販売手数料（円）",
    "simple_shipping_yen": "送料（円）",
    "repair_cost_yen": "修理費（円）",
    "parts_cost_yen": "部品代（円）",
    "iphone_model": "売却した業者",
    "iphone_capacity": "容量",
    "platform_memo": "メモ",
}


DISPLAY_COLUMNS = {
    "id": "ID",
    "product_name": TEXT["product_name"],
    "platform": TEXT["platform"],
    "currency_code": TEXT["currency_code"],
    "listing_date": TEXT["listing_date"],
    "sale_price_usd": TEXT["sale_price_usd"],
    "buyer_shipping_usd": TEXT["buyer_shipping_usd"],
    "exchange_rate": TEXT["exchange_rate"],
    "usd_jpy_rate": TEXT["usd_jpy_rate"],
    "purchase_price_yen": TEXT["purchase_price_yen"],
    "domestic_shipping_yen": TEXT["domestic_shipping_yen"],
    "international_shipping_yen": TEXT["international_shipping_yen"],
    "packaging_yen": TEXT["packaging_yen"],
    "other_cost_yen": TEXT["other_cost_yen"],
    "ebay_fee_rate": TEXT["ebay_fee_rate"],
    "promoted_listing_rate": TEXT["promoted_listing_rate"],
    "exchange_spread_rate": TEXT["exchange_spread_rate"],
    "fixed_fee_usd": TEXT["fixed_fee_usd"],
    "target_profit_yen": TEXT["target_profit_yen"],
    "profit_yen": TEXT["profit_yen"],
    "profit_margin": TEXT["profit_margin"],
    "roi": TEXT["roi"],
    "gross_sales_yen": TEXT["gross_sales_yen"],
    "break_even_sale_price_usd": TEXT["break_even_sale_price_usd"],
    "target_sale_price_usd": TEXT["target_sale_price_usd"],
    "search_keyword": TEXT["search_keyword"],
    "monthly_sales": TEXT["monthly_sales"],
    "competitor_count": TEXT["competitor_count"],
    "product_url": TEXT["product_url"],
    "research_shipping_weight_g": TEXT["research_shipping_weight_g"],
    "inventory_risk": TEXT["inventory_risk"],
    "research_memo": TEXT["research_memo"],
    "sku": TEXT["sku"],
    "source_url": TEXT["source_url"],
    "destination_country": TEXT["destination_country"],
    "sale_price_yen": TEXT["sale_price_yen"],
    "package_weight_g": TEXT["package_weight_g"],
    "package_length_cm": TEXT["package_length_cm"],
    "package_width_cm": TEXT["package_width_cm"],
    "package_height_cm": TEXT["package_height_cm"],
    "expected_shipping_carrier": TEXT["expected_shipping_carrier"],
    "expected_shipping_service": TEXT["expected_shipping_service"],
    "planned_shipping_yen": TEXT["planned_shipping_yen"],
    "planned_profit_margin": TEXT["planned_profit_margin"],
    "planned_base_shipping_yen": TEXT["planned_base_shipping_yen"],
    "planned_fuel_surcharge_yen": TEXT["planned_fuel_surcharge_yen"],
    "planned_additional_fee_yen": TEXT["planned_additional_fee_yen"],
    "planned_shipping_status": TEXT["planned_shipping_status"],
    "planned_shipping_reason": TEXT["planned_shipping_reason"],
    "rate_table_weight_g": TEXT["rate_table_weight_g"],
    "shipping_breakdown_json": TEXT["shipping_breakdown_json"],
    "overseas_fee_rate": TEXT["overseas_fee_rate"],
    "overseas_fee_yen": TEXT["overseas_fee_yen"],
    "other_fee_yen": TEXT["other_fee_yen"],
    "shipping_calculation_mode": TEXT["shipping_calculation_mode"],
    "volumetric_weight_g": TEXT["volumetric_weight_g"],
    "applied_weight_g": TEXT["applied_weight_g"],
    "billing_weight_g": TEXT["billing_weight_g"],
    "zonos_applied": TEXT["zonos_applied"],
    "zonos_base_shipping_yen": TEXT["zonos_base_shipping_yen"],
    "zonos_fee_base_yen": TEXT["zonos_fee_base_yen"],
    "zonos_fee_rate_percent": TEXT["zonos_fee_rate_percent"],
    "zonos_fee_yen": TEXT["zonos_fee_yen"],
    "zonos_duty_rate_percent": TEXT["zonos_duty_rate_percent"],
    "zonos_duty_base_yen": TEXT["zonos_duty_base_yen"],
    "zonos_duty_yen": TEXT["zonos_duty_yen"],
    "zonos_total_shipping_yen": TEXT["zonos_total_shipping_yen"],
    "zonos_config_effective_from": TEXT["zonos_config_effective_from"],
    "zonos_config_effective_to": TEXT["zonos_config_effective_to"],
    "registered_at": TEXT["registered_at"],
    "sales_fee_input_mode": TEXT["sales_fee_input_mode"],
    "sales_fee_rate": TEXT["sales_fee_rate"],
    "sales_fee_yen": TEXT["sales_fee_yen"],
    "simple_shipping_yen": TEXT["simple_shipping_yen"],
    "repair_cost_yen": TEXT["repair_cost_yen"],
    "parts_cost_yen": TEXT["parts_cost_yen"],
    "iphone_model": TEXT["iphone_model"],
    "iphone_capacity": TEXT["iphone_capacity"],
    "platform_memo": TEXT["platform_memo"],
    "calculated_at": TEXT["calculated_at"],
    "status": TEXT["status"],
    "sold_date": TEXT["sold_date"],
    "actual_sale_price_usd": TEXT["actual_sale_price_usd"],
    "actual_buyer_shipping_usd": TEXT["actual_buyer_shipping_usd"],
    "actual_ebay_fee_usd": TEXT["actual_ebay_fee_usd"],
    "actual_ad_fee_usd": TEXT["actual_ad_fee_usd"],
    "actual_fixed_fee_usd": TEXT["actual_fixed_fee_usd"],
    "actual_exchange_rate": TEXT["actual_exchange_rate"],
    "actual_usd_jpy_rate": TEXT["actual_usd_jpy_rate"],
    "actual_order_revenue_yen": TEXT["actual_order_revenue_yen"],
    "actual_purchase_price_yen": TEXT["actual_purchase_price_yen"],
    "actual_overseas_fee_yen": TEXT["actual_overseas_fee_yen"],
    "actual_copy_cost_yen": TEXT["actual_copy_cost_yen"],
    "actual_packaging_yen": TEXT["actual_packaging_yen"],
    "actual_other_cost_yen": TEXT["actual_other_cost_yen"],
    "actual_base_shipping_yen": TEXT["actual_base_shipping_yen"],
    "actual_fuel_surcharge_yen": TEXT["actual_fuel_surcharge_yen"],
    "actual_zonos_fee_yen": TEXT["actual_zonos_fee_yen"],
    "actual_duty_yen": TEXT["actual_duty_yen"],
    "actual_additional_fee_yen": TEXT["actual_additional_fee_yen"],
    "effective_ebay_fee_rate": TEXT["effective_ebay_fee_rate"],
    "effective_ad_fee_rate": TEXT["effective_ad_fee_rate"],
    "actual_shipping_yen": TEXT["actual_shipping_yen"],
    "shipping_carrier": TEXT["shipping_carrier"],
    "shipping_service": TEXT["shipping_service"],
    "shipping_weight_g": TEXT["shipping_weight_g"],
    "actual_profit_yen": TEXT["actual_profit_yen"],
    "actual_profit_margin": TEXT["actual_profit_margin"],
}


def yen(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f} \u5186"


def display_value(value: object) -> object:
    if value is None:
        return ""
    return value


def platform_value(row: dict[str, object]) -> str:
    return normalize_platform(row.get("platform"))


def is_simple_profit_platform(row: dict[str, object]) -> bool:
    return is_simple_platform(platform_value(row))


def listing_currency(row: dict[str, object]) -> str:
    return normalize_currency(row.get("currency_code"))


def foreign_amount_label(label: str, currency_code: str) -> str:
    currency = normalize_currency(currency_code)
    return f"{label}（{currency} / {currency_symbol(currency)}）"


def read_shared_exchange_rate(
    currency_code: str = DEFAULT_CURRENCY,
) -> float | None:
    currency = normalize_currency(currency_code)
    try:
        data = json.loads(SHARED_EXCHANGE_RATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None

    rates = data.get("rates")
    if isinstance(rates, dict) and isinstance(rates.get(currency), dict):
        rate = rates[currency].get("rate")
    elif currency == "USD":
        rate = data.get("usd_jpy")
    else:
        rate = None
    if not isinstance(rate, (int, float)) or rate <= 0:
        return None
    return float(rate)


def planned_usd_jpy_rate(row: dict[str, object]) -> float:
    stored = value(row, "usd_jpy_rate")
    if stored > 0:
        return stored
    if listing_currency(row) == "USD":
        planned = value(row, "exchange_rate")
        if planned > 0:
            return planned
    return read_shared_exchange_rate("USD") or DEFAULT_JPY_RATES["USD"]


def actual_usd_jpy_rate(row: dict[str, object]) -> float:
    stored = optional_value(row, "actual_usd_jpy_rate")
    if stored is not None and stored > 0:
        return stored
    if listing_currency(row) == "USD":
        actual = optional_value(row, "actual_exchange_rate")
        if actual is not None and actual > 0:
            return actual
    return planned_usd_jpy_rate(row)


def read_registration_event() -> dict[str, object] | None:
    if remote_database_is_configured():
        try:
            with get_connection() as connection:
                row = connection.execute(
                    """
                    SELECT id, product_name, created_at
                    FROM listings
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ).fetchone()
        except Exception:
            return None
        if row is None:
            return None
        return {
            "event_id": f"database:{row['id']}",
            "listing_id": int(row["id"]),
            "product_name": str(row["product_name"]),
            "created_at": str(row["created_at"]),
        }

    try:
        payload = json.loads(REGISTRATION_EVENT_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _watch_registration_event() -> None:
    event = read_registration_event()
    event_id = str((event or {}).get("event_id") or "")
    previous_id = str(st.session_state.get("last_registration_event_id") or "")
    if not event_id:
        return
    if not previous_id:
        st.session_state.last_registration_event_id = event_id
        return
    if event_id == previous_id:
        return
    st.session_state.last_registration_event_id = event_id
    st.session_state.registration_refresh_notice = event
    st.rerun()


if hasattr(st, "fragment"):
    render_registration_event_watcher = st.fragment(run_every="2s")(
        _watch_registration_event
    )
else:
    render_registration_event_watcher = _watch_registration_event


def get_connection():
    return get_database_connection(DB_PATH)


def init_db() -> None:
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
        existing = {row[1] for row in connection.execute("PRAGMA table_info(listings)")}
        required = {
            "currency_code": "TEXT NOT NULL DEFAULT 'USD'",
            "usd_jpy_rate": "REAL NOT NULL DEFAULT 0",
            "actual_usd_jpy_rate": "REAL",
            "actual_order_revenue_yen": "REAL",
            "actual_fee_schema_version": "INTEGER NOT NULL DEFAULT 1",
            "platform": "TEXT NOT NULL DEFAULT 'eBay'",
            "listing_price_usd": "REAL NOT NULL DEFAULT 0",
            "listing_price": "REAL NOT NULL DEFAULT 0",
            "buyer_shipping_usd": "REAL NOT NULL DEFAULT 0",
            "exchange_rate": "REAL NOT NULL DEFAULT 0",
            "purchase_price_yen": "REAL NOT NULL DEFAULT 0",
            "purchase_price": "REAL NOT NULL DEFAULT 0",
            "domestic_shipping_yen": "REAL NOT NULL DEFAULT 0",
            "international_shipping_yen": "REAL NOT NULL DEFAULT 0",
            "packaging_yen": "REAL NOT NULL DEFAULT 0",
            "other_cost_yen": "REAL NOT NULL DEFAULT 0",
            "expected_shipping": "REAL NOT NULL DEFAULT 0",
            "ebay_fee_yen": "REAL NOT NULL DEFAULT 0",
            "ebay_fee_rate": "REAL NOT NULL DEFAULT 0",
            "ad_fee_yen": "REAL NOT NULL DEFAULT 0",
            "promoted_listing_rate": "REAL NOT NULL DEFAULT 0",
            "exchange_spread_rate": "REAL NOT NULL DEFAULT 0",
            "fixed_fee_usd": "REAL NOT NULL DEFAULT 0",
            "target_profit_yen": "REAL NOT NULL DEFAULT 0",
            "expected_profit_yen": "REAL NOT NULL DEFAULT 0",
            "profit_yen": "REAL NOT NULL DEFAULT 0",
            "profit_margin": "REAL NOT NULL DEFAULT 0",
            "roi": "REAL",
            "gross_sales_yen": "REAL NOT NULL DEFAULT 0",
            "break_even_sale_price_usd": "REAL",
            "target_sale_price_usd": "REAL",
            "search_keyword": "TEXT NOT NULL DEFAULT ''",
            "monthly_sales": "REAL NOT NULL DEFAULT 0",
            "competitor_count": "REAL NOT NULL DEFAULT 0",
            "product_url": "TEXT NOT NULL DEFAULT ''",
            "research_shipping_weight_g": "REAL NOT NULL DEFAULT 0",
            "inventory_risk": "TEXT NOT NULL DEFAULT ''",
            "research_memo": "TEXT NOT NULL DEFAULT ''",
            "calculated_at": "TEXT",
            "actual_sale_price_usd": "REAL",
            "actual_sale_price": "REAL",
            "actual_buyer_shipping_usd": "REAL",
            "actual_ebay_fee_usd": "REAL",
            "actual_ad_fee_usd": "REAL",
            "actual_fixed_fee_usd": "REAL",
            "actual_exchange_rate": "REAL",
            "actual_purchase_price_yen": "REAL",
            "actual_overseas_fee_yen": "REAL",
            "actual_copy_cost_yen": "REAL",
            "actual_packaging_yen": "REAL",
            "actual_other_cost_yen": "REAL",
            "actual_base_shipping_yen": "REAL",
            "actual_fuel_surcharge_yen": "REAL",
            "actual_zonos_fee_yen": "REAL",
            "actual_duty_yen": "REAL",
            "actual_additional_fee_yen": "REAL",
            "effective_ebay_fee_rate": "REAL",
            "effective_ad_fee_rate": "REAL",
            "actual_shipping_yen": "REAL",
            "actual_shipping": "REAL",
            "shipping_carrier": "TEXT",
            "shipping_service": "TEXT",
            "shipping_weight_g": "REAL",
            "actual_profit_yen": "REAL",
            "actual_profit": "REAL",
            "actual_profit_margin": "REAL",
            "sold_date": "TEXT",
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
        for column, definition in required.items():
            if column not in existing:
                connection.execute(f"ALTER TABLE listings ADD COLUMN {column} {definition}")
        connection.execute(
            "UPDATE listings SET platform = ? WHERE platform = ?",
            (PLATFORM_IPHONE_RESALE, "その他"),
        )


def value(row: dict[str, object], key: str, fallback: str | None = None) -> float:
    raw = row.get(key)
    if raw in (None, "") and fallback:
        raw = row.get(fallback)
    return float(raw or 0)


def optional_value(row: dict[str, object], key: str) -> float | None:
    raw = row.get(key)
    if raw in (None, ""):
        return None
    return float(raw)


def usd_from_yen(value_yen: float, exchange_rate: float) -> float:
    if exchange_rate <= 0:
        return 0
    return value_yen / exchange_rate


def actual_fee_schema_version(row: dict[str, object]) -> int:
    raw = row.get("actual_fee_schema_version")
    try:
        return int(raw or ACTUAL_FEE_SCHEMA_LEGACY)
    except (TypeError, ValueError):
        return ACTUAL_FEE_SCHEMA_LEGACY


def actual_transaction_fee_usd(row: dict[str, object]) -> float | None:
    transaction_fee = optional_value(row, "actual_ebay_fee_usd")
    if transaction_fee is None:
        return None
    if actual_fee_schema_version(row) >= ACTUAL_FEE_SCHEMA_SEPARATE:
        return transaction_fee
    fixed_fee = optional_value(row, "actual_fixed_fee_usd") or 0.0
    return max(0.0, transaction_fee - fixed_fee)


def calculate_effective_rates(
    actual_sale_price: float,
    actual_ebay_fee_usd: float,
    actual_ad_fee_usd: float,
    actual_fixed_fee_usd: float,
    product_exchange_rate: float = 1.0,
    usd_jpy_exchange_rate: float = 1.0,
) -> tuple[float | None, float | None]:
    sale_price_yen = actual_sale_price * product_exchange_rate
    if sale_price_yen <= 0:
        return None, None

    effective_ebay_fee_rate = (
        actual_ebay_fee_usd
        * usd_jpy_exchange_rate
        / sale_price_yen
        * 100
    )
    effective_ad_fee_rate = (
        actual_ad_fee_usd
        * usd_jpy_exchange_rate
        / sale_price_yen
        * 100
    )
    return effective_ebay_fee_rate, effective_ad_fee_rate


def fetch_listings() -> list[dict[str, object]]:
    init_db()
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM listings
            ORDER BY COALESCE(calculated_at, created_at) DESC, id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def calculate_order_revenue_yen(
    product_exchange_rate: float,
    actual_sale_price: float,
    actual_buyer_shipping: float,
    actual_ebay_fee_usd: float,
    actual_ad_fee_usd: float,
    actual_fixed_fee_usd: float,
    usd_jpy_exchange_rate: float,
) -> float:
    order_total_yen = (
        actual_sale_price + actual_buyer_shipping
    ) * product_exchange_rate
    usd_fees_yen = (
        actual_ebay_fee_usd
        + actual_ad_fee_usd
        + actual_fixed_fee_usd
    ) * usd_jpy_exchange_rate
    return order_total_yen - usd_fees_yen


def calculate_actual_profit(
    row: dict[str, object],
    exchange_rate: float,
    actual_sale_price_usd: float,
    actual_buyer_shipping_usd: float,
    actual_ebay_fee_usd: float,
    actual_ad_fee_usd: float,
    actual_fixed_fee_usd: float,
    actual_usd_jpy_rate: float,
    actual_shipping_yen: float,
    actual_costs: dict[str, float | None] | None = None,
) -> float:
    actual_costs = actual_costs or {}

    def resolved_cost(actual_key: str, planned_key: str, fallback: str | None = None) -> float:
        raw = actual_costs.get(actual_key)
        if raw is not None:
            return float(raw)
        return value(row, planned_key, fallback)

    if is_simple_profit_platform(row):
        actual_sale_price_yen = actual_sale_price_usd
        if platform_value(row) == PLATFORM_IPHONE_RESALE:
            return (
                actual_sale_price_yen
                - resolved_cost(
                    "actual_purchase_price_yen",
                    "purchase_price_yen",
                    "purchase_price",
                )
                - actual_shipping_yen
            )
        return (
            actual_sale_price_yen
            - resolved_cost(
                "actual_purchase_price_yen",
                "purchase_price_yen",
                "purchase_price",
            )
            - resolved_cost(
                "actual_sales_fee_yen",
                "sales_fee_yen",
                "ebay_fee_yen",
            )
            - actual_shipping_yen
            - resolved_cost("actual_other_cost_yen", "other_cost_yen")
            - resolved_cost("actual_repair_cost_yen", "repair_cost_yen")
            - resolved_cost("actual_parts_cost_yen", "parts_cost_yen")
        )

    order_revenue_yen = calculate_order_revenue_yen(
        exchange_rate,
        actual_sale_price_usd,
        actual_buyer_shipping_usd,
        actual_ebay_fee_usd,
        actual_ad_fee_usd,
        actual_fixed_fee_usd,
        actual_usd_jpy_rate,
    )
    gross_sales_yen = (
        actual_sale_price_usd + actual_buyer_shipping_usd
    ) * exchange_rate
    exchange_spread_yen = actual_costs.get("actual_overseas_fee_yen")
    if exchange_spread_yen is None:
        exchange_spread_yen = gross_sales_yen * value(row, "exchange_spread_rate") / 100
    return (
        order_revenue_yen
        - resolved_cost("actual_purchase_price_yen", "purchase_price_yen", "purchase_price")
        - resolved_cost("actual_copy_cost_yen", "domestic_shipping_yen")
        - actual_shipping_yen
        - resolved_cost("actual_packaging_yen", "packaging_yen")
        - resolved_cost("actual_other_cost_yen", "other_cost_yen")
        - float(exchange_spread_yen)
    )


def calculate_actual_profit_margin(
    row: dict[str, object],
    actual_profit_yen: float | None,
    actual_sale_price: float | None,
    actual_buyer_shipping_usd: float | None,
    actual_exchange_rate: float | None,
) -> float | None:
    if actual_profit_yen is None or actual_sale_price is None:
        return None
    if is_simple_profit_platform(row):
        gross_sales_yen = float(actual_sale_price)
    else:
        rate = float(actual_exchange_rate or value(row, "exchange_rate"))
        gross_sales_yen = (
            float(actual_sale_price) + float(actual_buyer_shipping_usd or 0)
        ) * rate
    if gross_sales_yen <= 0:
        return None
    return float(actual_profit_yen) / gross_sales_yen * 100


def calculate_expected_values(row: dict[str, object]) -> dict[str, float | None]:
    if is_simple_profit_platform(row):
        gross_sales_yen = value(row, "listing_price_usd", "listing_price")
        product_cost_yen = value(row, "purchase_price_yen", "purchase_price")
        fee_mode = str(row.get("sales_fee_input_mode") or FEE_MODE_AMOUNT)
        if fee_mode not in (FEE_MODE_RATE, FEE_MODE_AMOUNT):
            fee_mode = FEE_MODE_AMOUNT
        calculation = calculate_simple_profit(
            platform=platform_value(row),
            sale_price_yen=gross_sales_yen,
            purchase_price_yen=product_cost_yen,
            fee_mode=fee_mode,
            fee_rate_percent=value(row, "sales_fee_rate", "ebay_fee_rate"),
            fee_amount_yen=value(row, "sales_fee_yen", "ebay_fee_yen"),
            shipping_yen=(
                value(row, "simple_shipping_yen")
                or value(row, "international_shipping_yen", "expected_shipping")
            ),
            other_cost_yen=value(row, "other_cost_yen"),
            repair_cost_yen=value(row, "repair_cost_yen"),
            parts_cost_yen=value(row, "parts_cost_yen"),
        )

        return {
            "ebay_fee_yen": calculation.sales_fee_yen,
            "ad_fee_yen": 0.0,
            "expected_profit_yen": calculation.profit_yen,
            "profit_yen": calculation.profit_yen,
            "profit_margin": calculation.profit_margin,
            "roi": calculation.roi,
            "gross_sales_yen": gross_sales_yen,
            "break_even_sale_price_usd": None,
            "target_sale_price_usd": None,
        }

    gross_sales_yen = (
        value(row, "listing_price_usd", "listing_price")
        + value(row, "buyer_shipping_usd")
    ) * value(row, "exchange_rate")
    ebay_fee_yen = gross_sales_yen * value(row, "ebay_fee_rate") / 100
    ad_fee_yen = gross_sales_yen * value(row, "promoted_listing_rate") / 100
    exchange_spread_yen = gross_sales_yen * value(row, "exchange_spread_rate") / 100
    fixed_fee_yen = value(row, "fixed_fee_usd") * planned_usd_jpy_rate(row)
    product_cost_yen = (
        value(row, "purchase_price_yen", "purchase_price")
        + value(row, "domestic_shipping_yen")
        + value(row, "international_shipping_yen", "expected_shipping")
        + value(row, "packaging_yen")
        + value(row, "other_cost_yen")
    )
    total_cost_yen = product_cost_yen + ebay_fee_yen + ad_fee_yen + exchange_spread_yen + fixed_fee_yen
    profit_yen = gross_sales_yen - total_cost_yen
    profit_margin = profit_yen / gross_sales_yen * 100 if gross_sales_yen else 0
    roi = profit_yen / product_cost_yen * 100 if product_cost_yen else None
    percentage_fee_rate = (
        value(row, "ebay_fee_rate")
        + value(row, "promoted_listing_rate")
        + value(row, "exchange_spread_rate")
    )
    remaining_rate = 1 - percentage_fee_rate / 100
    break_even_sale_price_usd = None
    target_sale_price_usd = None
    if value(row, "exchange_rate") > 0 and remaining_rate > 0:
        fixed_cost_for_price = product_cost_yen + fixed_fee_yen
        break_even_total_usd = fixed_cost_for_price / (value(row, "exchange_rate") * remaining_rate)
        target_total_usd = (fixed_cost_for_price + value(row, "target_profit_yen")) / (
            value(row, "exchange_rate") * remaining_rate
        )
        break_even_sale_price_usd = max(0, break_even_total_usd - value(row, "buyer_shipping_usd"))
        target_sale_price_usd = max(0, target_total_usd - value(row, "buyer_shipping_usd"))

    return {
        "ebay_fee_yen": ebay_fee_yen,
        "ad_fee_yen": ad_fee_yen,
        "expected_profit_yen": profit_yen,
        "profit_yen": profit_yen,
        "profit_margin": profit_margin,
        "roi": roi,
        "gross_sales_yen": gross_sales_yen,
        "break_even_sale_price_usd": break_even_sale_price_usd,
        "target_sale_price_usd": target_sale_price_usd,
    }


def actual_fee_defaults(row: dict[str, object], exchange_rate: float) -> dict[str, float]:
    actual_sale_price_usd = optional_value(row, "actual_sale_price_usd")
    if actual_sale_price_usd is None:
        actual_sale_price_usd = optional_value(row, "actual_sale_price")
    if actual_sale_price_usd is None:
        actual_sale_price_usd = value(row, "listing_price_usd", "listing_price")

    if is_simple_profit_platform(row):
        actual_shipping_yen = optional_value(row, "actual_shipping_yen")
        if actual_shipping_yen is None:
            actual_shipping_yen = optional_value(row, "actual_shipping")
        if actual_shipping_yen is None:
            actual_shipping_yen = (
                value(row, "simple_shipping_yen")
                or value(row, "international_shipping_yen", "expected_shipping")
            )
        return {
            "actual_sale_price_usd": actual_sale_price_usd,
            "actual_buyer_shipping_usd": 0.0,
            "actual_ebay_fee_usd": 0.0,
            "actual_ad_fee_usd": 0.0,
            "actual_fixed_fee_usd": 0.0,
            "actual_shipping_yen": actual_shipping_yen,
        }

    actual_buyer_shipping_usd = optional_value(row, "actual_buyer_shipping_usd")
    if actual_buyer_shipping_usd is None:
        actual_buyer_shipping_usd = value(row, "buyer_shipping_usd")

    fee_exchange_rate = actual_usd_jpy_rate(row) or exchange_rate
    actual_fixed_fee_usd = optional_value(row, "actual_fixed_fee_usd")
    if actual_fixed_fee_usd is None:
        actual_fixed_fee_usd = value(row, "fixed_fee_usd")

    actual_ebay_fee_usd = optional_value(row, "actual_ebay_fee_usd")
    if actual_ebay_fee_usd is None:
        actual_ebay_fee_usd = usd_from_yen(
            value(row, "ebay_fee_yen"),
            fee_exchange_rate,
        )
    elif actual_fee_schema_version(row) < ACTUAL_FEE_SCHEMA_SEPARATE:
        actual_ebay_fee_usd = max(
            0.0,
            actual_ebay_fee_usd - actual_fixed_fee_usd,
        )

    actual_ad_fee_usd = optional_value(row, "actual_ad_fee_usd")
    if actual_ad_fee_usd is None:
        actual_ad_fee_usd = usd_from_yen(
            value(row, "ad_fee_yen"),
            fee_exchange_rate,
        )

    actual_shipping_yen = optional_value(row, "actual_shipping_yen")
    if actual_shipping_yen is None:
        actual_shipping_yen = optional_value(row, "actual_shipping")
    if actual_shipping_yen is None:
        actual_shipping_yen = value(row, "international_shipping_yen", "expected_shipping")

    return {
        "actual_sale_price_usd": actual_sale_price_usd,
        "actual_buyer_shipping_usd": actual_buyer_shipping_usd,
        "actual_ebay_fee_usd": actual_ebay_fee_usd,
        "actual_ad_fee_usd": actual_ad_fee_usd,
        "actual_fixed_fee_usd": actual_fixed_fee_usd,
        "actual_shipping_yen": actual_shipping_yen,
    }


def actual_detail_defaults(
    row: dict[str, object],
    exchange_rate: float,
    actual_sale_price_usd: float,
    actual_buyer_shipping_usd: float,
    actual_shipping_yen: float,
) -> dict[str, float]:
    if is_simple_profit_platform(row):
        def simple_existing_or(key: str, fallback: float) -> float:
            stored = optional_value(row, key)
            return fallback if stored is None else stored

        is_iphone_resale = platform_value(row) == PLATFORM_IPHONE_RESALE
        return {
            "actual_exchange_rate": 1.0,
            "actual_purchase_price_yen": simple_existing_or(
                "actual_purchase_price_yen",
                value(row, "purchase_price_yen", "purchase_price"),
            ),
            "actual_overseas_fee_yen": 0.0,
            "actual_copy_cost_yen": 0.0,
            "actual_packaging_yen": 0.0,
            "actual_other_cost_yen": 0.0
            if is_iphone_resale
            else simple_existing_or(
                "actual_other_cost_yen",
                value(row, "other_cost_yen"),
            ),
            "actual_base_shipping_yen": actual_shipping_yen,
            "actual_fuel_surcharge_yen": 0.0,
            "actual_zonos_fee_yen": 0.0,
            "actual_duty_yen": 0.0,
            "actual_additional_fee_yen": 0.0,
            "actual_sales_fee_yen": 0.0
            if is_iphone_resale
            else simple_existing_or(
                "actual_sales_fee_yen",
                value(row, "sales_fee_yen", "ebay_fee_yen"),
            ),
            "actual_repair_cost_yen": 0.0,
            "actual_parts_cost_yen": 0.0,
        }

    actual_rate = optional_value(row, "actual_exchange_rate")
    if actual_rate is None or actual_rate <= 0:
        actual_rate = value(row, "exchange_rate") or exchange_rate
    gross_sales_yen = (
        actual_sale_price_usd + actual_buyer_shipping_usd
    ) * actual_rate
    planned_fuel = value(row, "planned_fuel_surcharge_yen")
    planned_zonos = value(row, "zonos_fee_yen")
    planned_duty = value(row, "zonos_duty_yen")
    planned_additional = value(row, "planned_additional_fee_yen")
    planned_base = value(row, "planned_base_shipping_yen") or value(row, "zonos_base_shipping_yen")
    if planned_base == 0:
        planned_base = max(
            0.0,
            actual_shipping_yen - planned_fuel - planned_zonos - planned_duty - planned_additional,
        )

    def existing_or(key: str, fallback: float) -> float:
        stored = optional_value(row, key)
        return fallback if stored is None else stored

    return {
        "actual_exchange_rate": actual_rate,
        "actual_purchase_price_yen": existing_or(
            "actual_purchase_price_yen",
            value(row, "purchase_price_yen", "purchase_price"),
        ),
        "actual_overseas_fee_yen": existing_or(
            "actual_overseas_fee_yen",
            gross_sales_yen * value(row, "exchange_spread_rate") / 100,
        ),
        "actual_copy_cost_yen": existing_or("actual_copy_cost_yen", value(row, "domestic_shipping_yen")),
        "actual_packaging_yen": existing_or("actual_packaging_yen", value(row, "packaging_yen")),
        "actual_other_cost_yen": existing_or("actual_other_cost_yen", value(row, "other_cost_yen")),
        "actual_base_shipping_yen": existing_or("actual_base_shipping_yen", planned_base),
        "actual_fuel_surcharge_yen": existing_or("actual_fuel_surcharge_yen", planned_fuel),
        "actual_zonos_fee_yen": existing_or("actual_zonos_fee_yen", planned_zonos),
        "actual_duty_yen": existing_or("actual_duty_yen", planned_duty),
        "actual_additional_fee_yen": existing_or("actual_additional_fee_yen", planned_additional),
    }


def recalculate_sold_actual_profits(exchange_rate: float) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM listings
            WHERE status = ?
            """,
            (STATUS_SOLD,),
        ).fetchall()

        for source in rows:
            row = dict(source)
            actual = actual_fee_defaults(row, exchange_rate)
            fee_exchange_rate = actual_usd_jpy_rate(row)
            if is_simple_profit_platform(row):
                effective_ebay_fee_rate = None
                effective_ad_fee_rate = None
            else:
                effective_ebay_fee_rate, effective_ad_fee_rate = calculate_effective_rates(
                    actual["actual_sale_price_usd"],
                    actual["actual_ebay_fee_usd"],
                    actual["actual_ad_fee_usd"],
                    actual["actual_fixed_fee_usd"],
                    value(row, "actual_exchange_rate") or value(row, "exchange_rate"),
                    fee_exchange_rate,
                )
            actual_details = actual_detail_defaults(
                row,
                exchange_rate,
                actual["actual_sale_price_usd"],
                actual["actual_buyer_shipping_usd"],
                actual["actual_shipping_yen"],
            )
            order_revenue = None
            if not is_simple_profit_platform(row):
                order_revenue = calculate_order_revenue_yen(
                    float(actual_details["actual_exchange_rate"]),
                    actual["actual_sale_price_usd"],
                    actual["actual_buyer_shipping_usd"],
                    actual["actual_ebay_fee_usd"],
                    actual["actual_ad_fee_usd"],
                    actual["actual_fixed_fee_usd"],
                    fee_exchange_rate,
                )
            actual_profit = calculate_actual_profit(
                row,
                actual_details["actual_exchange_rate"],
                actual["actual_sale_price_usd"],
                actual["actual_buyer_shipping_usd"],
                actual["actual_ebay_fee_usd"],
                actual["actual_ad_fee_usd"],
                actual["actual_fixed_fee_usd"],
                fee_exchange_rate,
                actual["actual_shipping_yen"],
                actual_details,
            )
            actual_profit_margin = calculate_actual_profit_margin(
                row,
                actual_profit,
                actual["actual_sale_price_usd"],
                actual["actual_buyer_shipping_usd"],
                actual_details["actual_exchange_rate"],
            )
            connection.execute(
                """
                UPDATE listings
                SET actual_sale_price_usd = ?,
                    actual_sale_price = ?,
                    actual_buyer_shipping_usd = ?,
                    actual_ebay_fee_usd = ?,
                    actual_ad_fee_usd = ?,
                    actual_fixed_fee_usd = ?,
                    actual_fee_schema_version = ?,
                    actual_usd_jpy_rate = ?,
                    actual_order_revenue_yen = ?,
                    effective_ebay_fee_rate = ?,
                    effective_ad_fee_rate = ?,
                    actual_shipping_yen = ?,
                    actual_shipping = ?,
                    actual_profit_yen = ?,
                    actual_profit = ?,
                    actual_profit_margin = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    actual["actual_sale_price_usd"],
                    actual["actual_sale_price_usd"],
                    actual["actual_buyer_shipping_usd"],
                    actual["actual_ebay_fee_usd"],
                    actual["actual_ad_fee_usd"],
                    actual["actual_fixed_fee_usd"],
                    ACTUAL_FEE_SCHEMA_SEPARATE,
                    fee_exchange_rate if not is_simple_profit_platform(row) else None,
                    order_revenue,
                    effective_ebay_fee_rate,
                    effective_ad_fee_rate,
                    actual["actual_shipping_yen"],
                    actual["actual_shipping_yen"],
                    actual_profit,
                    actual_profit,
                    actual_profit_margin,
                    now,
                    row["id"],
                ),
            )


def fetch_dashboard() -> dict[str, float | int]:
    init_db()
    with get_connection() as connection:
        active_count = connection.execute(
            "SELECT COUNT(*) FROM listings WHERE status = ?",
            (STATUS_ACTIVE,),
        ).fetchone()[0]
        sold_count = connection.execute(
            "SELECT COUNT(*) FROM listings WHERE status = ?",
            (STATUS_SOLD,),
        ).fetchone()[0]
        cancelled_count = connection.execute(
            "SELECT COUNT(*) FROM listings WHERE status = ?",
            (STATUS_CANCELLED,),
        ).fetchone()[0]
        registered_count = connection.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    return {
        "active_count": int(active_count or 0),
        "sold_count": int(sold_count or 0),
        "cancelled_count": int(cancelled_count or 0),
        "registered_count": int(registered_count or 0),
    }


WEIGHT_BANDS = (
    ("0～250g", 0, 250),
    ("251～500g", 251, 500),
    ("501g～1kg", 501, 1000),
    ("1kg超～2kg", 1001, 2000),
    ("2kg超～5kg", 2001, 5000),
    ("5kg超", 5001, None),
)


def parse_date_value(raw: object) -> date | None:
    if raw in (None, ""):
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def safe_percent(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator * 100


def percent_text(value: float | None) -> str:
    if value is None:
        return "算出不可"
    return f"{value:.1f}%"


def signed_yen(value: float | int | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.0f} 円"


def csv_bytes(rows: list[dict[str, object]]) -> bytes:
    if not rows:
        return b""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def sold_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        normalize_row(row)
        for row in rows
        if str(row.get("status")) == STATUS_SOLD
        and optional_value(row, "actual_profit_yen") is not None
    ]


def row_actual_exchange_rate(row: dict[str, object]) -> float:
    actual_rate = optional_value(row, "actual_exchange_rate")
    if actual_rate is not None and actual_rate > 0:
        return actual_rate
    return value(row, "exchange_rate")


def planned_sales_yen(row: dict[str, object]) -> float:
    if is_simple_profit_platform(row):
        return value(row, "listing_price_usd", "listing_price")
    return (
        value(row, "listing_price_usd", "listing_price")
        + value(row, "buyer_shipping_usd")
    ) * value(row, "exchange_rate")


def planned_shipping_amount(row: dict[str, object]) -> float:
    amount = optional_value(row, "planned_shipping_yen")
    if amount is not None and amount > 0:
        return amount
    amount = optional_value(row, "international_shipping_yen")
    if amount is not None and amount > 0:
        return amount
    return value(row, "expected_shipping")


def actual_sales_yen(row: dict[str, object]) -> float | None:
    actual_sale = optional_value(row, "actual_sale_price_usd")
    if actual_sale is None:
        actual_sale = optional_value(row, "actual_sale_price")
    if actual_sale is None:
        return None
    if is_simple_profit_platform(row):
        return actual_sale
    actual_shipping_usd = optional_value(row, "actual_buyer_shipping_usd")
    if actual_shipping_usd is None:
        if value(row, "buyer_shipping_usd") != 0:
            return None
        actual_shipping_usd = 0.0
    exchange_rate = row_actual_exchange_rate(row)
    if exchange_rate <= 0:
        return None
    return (actual_sale + actual_shipping_usd) * exchange_rate


def actual_cost_components(row: dict[str, object]) -> dict[str, float | None]:
    if is_simple_profit_platform(row):
        if platform_value(row) == PLATFORM_IPHONE_RESALE:
            return {
                "仕入れ価格": optional_value(row, "actual_purchase_price_yen"),
            }
        return {
            "仕入れ価格": optional_value(row, "actual_purchase_price_yen"),
            "販売手数料": optional_value(row, "actual_sales_fee_yen"),
            "その他コスト": optional_value(row, "actual_other_cost_yen"),
        }

    fee_exchange_rate = actual_usd_jpy_rate(row)
    transaction_fee_usd = actual_transaction_fee_usd(row)
    transaction_fee_yen = (
        None
        if transaction_fee_usd is None
        else transaction_fee_usd * fee_exchange_rate
    )
    return {
        "仕入れ価格": optional_value(row, "actual_purchase_price_yen"),
        "eBay取引手数料": transaction_fee_yen,
        "広告費": None
        if optional_value(row, "actual_ad_fee_usd") is None
        else optional_value(row, "actual_ad_fee_usd") * fee_exchange_rate,
        "固定手数料": None
        if optional_value(row, "actual_fixed_fee_usd") is None
        else optional_value(row, "actual_fixed_fee_usd") * fee_exchange_rate,
        "海外手数料・決済コスト": optional_value(row, "actual_overseas_fee_yen"),
        "コピー代": optional_value(row, "actual_copy_cost_yen"),
        "梱包資材費": optional_value(row, "actual_packaging_yen"),
        "その他コスト": optional_value(row, "actual_other_cost_yen"),
    }


def planned_cost_components(row: dict[str, object]) -> dict[str, float]:
    if is_simple_profit_platform(row):
        if platform_value(row) == PLATFORM_IPHONE_RESALE:
            return {
                "仕入れ価格": value(row, "purchase_price_yen", "purchase_price"),
            }
        return {
            "仕入れ価格": value(row, "purchase_price_yen", "purchase_price"),
            "販売手数料": value(row, "sales_fee_yen", "ebay_fee_yen"),
            "その他コスト": value(row, "other_cost_yen"),
        }

    return {
        "仕入れ価格": value(row, "purchase_price_yen", "purchase_price"),
        "eBay取引手数料": value(row, "ebay_fee_yen"),
        "広告費": value(row, "ad_fee_yen"),
        "固定手数料": value(row, "fixed_fee_usd") * planned_usd_jpy_rate(row),
        "海外手数料・決済コスト": planned_sales_yen(row) * value(row, "exchange_spread_rate") / 100,
        "コピー代": value(row, "domestic_shipping_yen"),
        "梱包資材費": value(row, "packaging_yen"),
        "その他コスト": value(row, "other_cost_yen"),
    }


def append_variance_row(
    rows: list[dict[str, object]],
    label: str,
    planned: float,
    actual: float | None,
    *,
    revenue: bool = False,
    missing_message: str | None = None,
) -> None:
    if actual is None:
        rows.append(
            {
                "項目": label,
                "予定値": planned,
                "実績値": "未入力",
                "差額": "比較対象外",
                "利益への影響": 0.0,
                "状態": "実績データ不足",
                "説明": missing_message or f"{label}の実績値が未入力です。",
            }
        )
        return
    diff = actual - planned
    impact = diff if revenue else -diff
    rows.append(
        {
            "項目": label,
            "予定値": planned,
            "実績値": actual,
            "差額": diff,
            "利益への影響": impact,
            "状態": "利益増加" if impact > 0 else "利益減少" if impact < 0 else "差額なし",
            "説明": (
                f"{label}が予定より{yen(abs(diff))}"
                f"{'高い' if diff > 0 else '低い' if diff < 0 else '同じ'}ため、"
                f"利益へ{signed_yen(impact)}の影響です。"
            ),
        }
    )


def append_shipping_variances(rows: list[dict[str, object]], row: dict[str, object]) -> None:
    planned_total = planned_shipping_amount(row)
    actual_total = optional_value(row, "actual_shipping_yen")
    component_specs = (
        ("基本送料", value(row, "planned_base_shipping_yen") or value(row, "zonos_base_shipping_yen"), "actual_base_shipping_yen"),
        ("燃油サーチャージ", value(row, "planned_fuel_surcharge_yen"), "actual_fuel_surcharge_yen"),
        ("Zonos手数料", value(row, "zonos_fee_yen"), "actual_zonos_fee_yen"),
        ("関税", value(row, "zonos_duty_yen"), "actual_duty_yen"),
        ("その他追加料金", value(row, "planned_additional_fee_yen"), "actual_additional_fee_yen"),
    )
    applicable = [spec for spec in component_specs if spec[1] != 0 or optional_value(row, spec[2]) is not None]
    all_components_known = bool(applicable) and all(optional_value(row, spec[2]) is not None for spec in applicable)

    if actual_total is None or not all_components_known:
        append_variance_row(rows, "送料", planned_total, actual_total)
        for label, planned, actual_key in applicable:
            if optional_value(row, actual_key) is None:
                append_variance_row(
                    rows,
                    label,
                    planned,
                    None,
                    missing_message=f"{label}の実績内訳が未入力です。送料合計の差額だけを分析します。",
                )
        return

    planned_known = 0.0
    actual_known = 0.0
    for label, planned, actual_key in applicable:
        actual = optional_value(row, actual_key)
        planned_known += planned
        actual_known += float(actual or 0)
        append_variance_row(rows, label, planned, actual)
    planned_other = planned_total - planned_known
    actual_other = actual_total - actual_known
    if abs(planned_other) >= 0.5 or abs(actual_other) >= 0.5:
        append_variance_row(rows, "その他送料", planned_other, actual_other)


def profit_variance_rows(row: dict[str, object]) -> list[dict[str, object]]:
    planned_profit = value(row, "profit_yen", "expected_profit_yen")
    actual_profit = optional_value(row, "actual_profit_yen")
    if actual_profit is None:
        actual_profit = optional_value(row, "actual_profit")
    rows: list[dict[str, object]] = []

    planned_sales = planned_sales_yen(row)
    actual_sale_usd = optional_value(row, "actual_sale_price_usd")
    if actual_sale_usd is None:
        actual_sale_usd = optional_value(row, "actual_sale_price")
    if is_simple_profit_platform(row):
        append_variance_row(rows, "販売価格", planned_sales, actual_sale_usd, revenue=True)
    elif actual_sale_usd is None:
        append_variance_row(rows, "販売価格・購入者送料", planned_sales, None, revenue=True)
        append_variance_row(rows, "為替レート", value(row, "exchange_rate"), None, revenue=True)
    else:
        actual_buyer_shipping_usd = optional_value(row, "actual_buyer_shipping_usd")
        if actual_buyer_shipping_usd is None and value(row, "buyer_shipping_usd") == 0:
            actual_buyer_shipping_usd = 0.0
        if actual_buyer_shipping_usd is None:
            append_variance_row(rows, "販売価格・購入者送料", planned_sales, None, revenue=True)
        else:
            planned_rate = value(row, "exchange_rate")
            actual_total_usd = actual_sale_usd + actual_buyer_shipping_usd
            price_sales_yen = actual_total_usd * planned_rate
            append_variance_row(rows, "販売価格・購入者送料", planned_sales, price_sales_yen, revenue=True)
            actual_rate = optional_value(row, "actual_exchange_rate")
            if actual_rate is None:
                append_variance_row(
                    rows,
                    "為替レート",
                    planned_rate,
                    None,
                    revenue=True,
                    missing_message="売却時の実績為替レートが保存されていません。",
                )
                rows[-1]["予定値"] = f"{planned_rate:.4f}"
            else:
                fx_impact = actual_total_usd * (actual_rate - planned_rate)
                append_variance_row(
                    rows,
                    "為替レート",
                    planned_rate,
                    actual_rate,
                    revenue=True,
                )
                rows[-1]["予定値"] = f"{planned_rate:.4f}"
                rows[-1]["実績値"] = f"{actual_rate:.4f}"
                rows[-1]["差額"] = f"{actual_rate - planned_rate:+.4f}"
                rows[-1]["利益への影響"] = fx_impact
                rows[-1]["状態"] = "利益増加" if fx_impact > 0 else "利益減少" if fx_impact < 0 else "差額なし"
                rows[-1]["説明"] = f"為替差により利益へ{signed_yen(fx_impact)}の影響です。"

    append_shipping_variances(rows, row)

    planned_costs = planned_cost_components(row)
    actual_costs = actual_cost_components(row)
    for label, planned in planned_costs.items():
        actual = actual_costs.get(label)
        append_variance_row(rows, label, planned, actual)

    rows.sort(key=lambda item: abs(float(item["利益への影響"] or 0)), reverse=True)
    return rows


def month_key(raw: object) -> str | None:
    sold = parse_date_value(raw)
    return None if sold is None else sold.strftime("%Y-%m")


def month_start(year: int, month: int) -> date:
    return date(year, month, 1)


def add_months(base: date, months: int) -> date:
    month = base.month - 1 + months
    year = base.year + month // 12
    month = month % 12 + 1
    return date(year, month, 1)


def period_bounds(label: str, year: int, month: int, start: date, end: date) -> tuple[date, date]:
    today = date.today()
    this_month = date(today.year, today.month, 1)
    if label == "今月":
        return this_month, add_months(this_month, 1) - timedelta(days=1)
    if label == "先月":
        prev = add_months(this_month, -1)
        return prev, this_month - timedelta(days=1)
    if label == "過去3か月":
        return add_months(this_month, -2), add_months(this_month, 1) - timedelta(days=1)
    if label == "今年":
        return date(today.year, 1, 1), date(today.year, 12, 31)
    if label == "年月指定":
        selected = month_start(year, month)
        return selected, add_months(selected, 1) - timedelta(days=1)
    if label == "期間指定":
        return start, end
    return date(1900, 1, 1), date(2999, 12, 31)


def filter_by_period(rows: list[dict[str, object]], start: date, end: date) -> tuple[list[dict[str, object]], int]:
    filtered = []
    missing_sold_date = 0
    for row in rows:
        sold = parse_date_value(row.get("sold_date"))
        if sold is None:
            missing_sold_date += 1
            continue
        if start <= sold <= end:
            filtered.append(row)
    return filtered, missing_sold_date


def aggregate_rows(rows: list[dict[str, object]]) -> dict[str, float | int | None]:
    def simple_sales_fee(row: dict[str, object]) -> float:
        if platform_value(row) == PLATFORM_IPHONE_RESALE:
            return 0.0
        stored = optional_value(row, "actual_sales_fee_yen")
        return stored if stored is not None else value(row, "sales_fee_yen", "ebay_fee_yen")

    def simple_other_cost(row: dict[str, object]) -> float:
        if platform_value(row) == PLATFORM_IPHONE_RESALE:
            return 0.0
        stored = optional_value(row, "actual_other_cost_yen")
        return stored if stored is not None else value(row, "other_cost_yen")

    count = len(rows)
    actual_sales_values = [actual_sales_yen(row) for row in rows if actual_sales_yen(row) is not None]
    sales = sum(actual_sales_values)
    buyer_shipping = sum((optional_value(row, "actual_buyer_shipping_usd") or 0) * row_actual_exchange_rate(row) for row in rows)
    purchase = sum(
        optional_value(row, "actual_purchase_price_yen")
        if optional_value(row, "actual_purchase_price_yen") is not None
        else value(row, "purchase_price_yen", "purchase_price")
        for row in rows
    )
    actual_shipping_values = [optional_value(row, "actual_shipping_yen") for row in rows if optional_value(row, "actual_shipping_yen") is not None]
    actual_shipping = sum(actual_shipping_values)
    ebay_fee = sum(
        simple_sales_fee(row)
        if is_simple_profit_platform(row)
        else (
            float(actual_transaction_fee_usd(row) or 0)
            * actual_usd_jpy_rate(row)
            if actual_transaction_fee_usd(row) is not None
            else 0.0
        )
        for row in rows
    )
    ad_fee = sum(
        (optional_value(row, "actual_ad_fee_usd") or 0)
        * actual_usd_jpy_rate(row)
        for row in rows
    )
    fixed_fee = sum(
        (optional_value(row, "actual_fixed_fee_usd") or 0)
        * actual_usd_jpy_rate(row)
        for row in rows
    )
    overseas_fee = sum(
        optional_value(row, "actual_overseas_fee_yen")
        if optional_value(row, "actual_overseas_fee_yen") is not None
        else (actual_sales_yen(row) or 0) * value(row, "exchange_spread_rate") / 100
        for row in rows
    )
    copy_cost = sum(
        optional_value(row, "actual_copy_cost_yen")
        if optional_value(row, "actual_copy_cost_yen") is not None
        else value(row, "domestic_shipping_yen")
        for row in rows
    )
    packaging = sum(
        optional_value(row, "actual_packaging_yen")
        if optional_value(row, "actual_packaging_yen") is not None
        else value(row, "packaging_yen")
        for row in rows
    )
    other = sum(
        simple_other_cost(row)
        for row in rows
    )
    zonos_fee = sum(
        optional_value(row, "actual_zonos_fee_yen")
        if optional_value(row, "actual_zonos_fee_yen") is not None
        else value(row, "zonos_fee_yen")
        for row in rows
    )
    duty = sum(
        optional_value(row, "actual_duty_yen")
        if optional_value(row, "actual_duty_yen") is not None
        else value(row, "zonos_duty_yen")
        for row in rows
    )
    additional_fee = sum(
        optional_value(row, "actual_additional_fee_yen")
        if optional_value(row, "actual_additional_fee_yen") is not None
        else value(row, "planned_additional_fee_yen")
        for row in rows
    )
    actual_profit = sum(optional_value(row, "actual_profit_yen") or optional_value(row, "actual_profit") or 0 for row in rows)
    # 実送料はZonos・関税・追加料金を含む合計として保存されるため、内訳を再加算しない。
    total_cost = (
        purchase + actual_shipping + ebay_fee + ad_fee + fixed_fee + overseas_fee
        + copy_cost + packaging + other
    )
    loss_rows = [row for row in rows if (optional_value(row, "actual_profit_yen") or 0) < 0]
    return {
        "売却件数": count,
        "売上合計": sales,
        "購入者送料": buyer_shipping,
        "仕入れ価格合計": purchase,
        "実送料合計": actual_shipping,
        "eBay取引手数料合計": ebay_fee,
        "広告費合計": ad_fee,
        "固定手数料合計": fixed_fee,
        "海外手数料・決済コスト合計": overseas_fee,
        "コピー代合計": copy_cost,
        "梱包資材費合計": packaging,
        "その他コスト合計": other,
        "Zonos手数料合計": zonos_fee,
        "関税合計": duty,
        "その他追加料金合計": additional_fee,
        "全費用合計": total_cost,
        "実利益合計": actual_profit,
        "平均利益": actual_profit / count if count else 0,
        "実利益率": safe_percent(actual_profit, sales),
        "黒字件数": sum(1 for row in rows if (optional_value(row, "actual_profit_yen") or 0) >= 0),
        "赤字件数": len(loss_rows),
        "赤字合計": sum(optional_value(row, "actual_profit_yen") or 0 for row in loss_rows),
        "実送料未入力件数": count - len(actual_shipping_values),
        "売上データ不足件数": count - len(actual_sales_values),
        "実績内訳不足件数": sum(
            1
            for row in rows
            if any(
                optional_value(row, key) is None
                for key in (
                    "actual_exchange_rate",
                    "actual_purchase_price_yen",
                    "actual_overseas_fee_yen",
                    "actual_copy_cost_yen",
                    "actual_packaging_yen",
                    "actual_other_cost_yen",
                )
            )
        ),
    }


def shipping_carrier_name(row: dict[str, object]) -> str:
    return str(row.get("shipping_carrier") or row.get("expected_shipping_carrier") or "未設定")


def shipping_service_name(row: dict[str, object]) -> str:
    return str(
        row.get("shipping_service")
        or row.get("expected_shipping_service")
        or "未設定"
    )


def default_actual_shipping_carrier(row: dict[str, object]) -> str:
    actual_carrier = str(row.get("shipping_carrier") or "")
    expected_carrier = str(row.get("expected_shipping_carrier") or "")
    service = str(
        row.get("shipping_service")
        or row.get("expected_shipping_service")
        or ""
    )
    carrier = actual_carrier or expected_carrier
    if (
        carrier in ("SpeedPAK", "SpeedPAK / CPaSS", "SpeedPAK／CPaSS")
        and "Economy" in service
    ):
        return "SpeedPAK Economy"
    return carrier


def weight_band(weight_g: float | None) -> str:
    if weight_g is None:
        return "重量未入力"
    for label, lower, upper in WEIGHT_BANDS:
        if weight_g >= lower and (upper is None or weight_g <= upper):
            return label
    return "重量未入力"


def aggregate_by_key(rows: list[dict[str, object]], key_func) -> list[dict[str, object]]:
    groups: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        groups.setdefault(str(key_func(row)), []).append(row)
    result = []
    for key, group in groups.items():
        summary = aggregate_rows(group)
        actual_shipping_values = [optional_value(row, "actual_shipping_yen") for row in group if optional_value(row, "actual_shipping_yen") is not None]
        planned_shipping_values = [planned_shipping_amount(row) for row in group]
        shipping_diff_values = [
            (optional_value(row, "actual_shipping_yen") or 0)
            - planned_shipping_amount(row)
            for row in group
            if optional_value(row, "actual_shipping_yen") is not None
        ]
        weights = [
            optional_value(row, "shipping_weight_g") or optional_value(row, "package_weight_g")
            for row in group
            if (optional_value(row, "shipping_weight_g") or optional_value(row, "package_weight_g")) is not None
        ]
        over_planned = sum(1 for diff in shipping_diff_values if diff > 0)
        row = {
            "区分": key,
            "発送件数": len(group),
            "実送料合計": summary["実送料合計"],
            "平均実送料": sum(actual_shipping_values) / len(actual_shipping_values) if actual_shipping_values else None,
            "予定送料合計": sum(planned_shipping_values),
            "平均予定送料": sum(planned_shipping_values) / len(planned_shipping_values) if planned_shipping_values else None,
            "送料差額合計": sum(shipping_diff_values),
            "平均送料差額": sum(shipping_diff_values) / len(shipping_diff_values) if shipping_diff_values else None,
            "売上合計": summary["売上合計"],
            "実利益合計": summary["実利益合計"],
            "平均実利益": summary["平均利益"],
            "実利益率": summary["実利益率"],
            "赤字件数": summary["赤字件数"],
            "平均重量": sum(weights) / len(weights) if weights else None,
            "平均配送日数": "データなし",
            "予定送料超過件数": over_planned,
            "実送料未入力件数": summary["実送料未入力件数"],
        }
        result.append(row)
    return sorted(result, key=lambda item: float(item.get("実利益合計") or 0), reverse=True)


def update_status(
    listing_id: int,
    status: str,
    actual_sale_price_usd: float | None,
    actual_buyer_shipping_usd: float | None,
    actual_ebay_fee_usd: float | None,
    actual_ad_fee_usd: float | None,
    actual_fixed_fee_usd: float | None,
    effective_ebay_fee_rate: float | None,
    effective_ad_fee_rate: float | None,
    actual_shipping_yen: float | None,
    shipping_carrier: str | None,
    shipping_service: str | None,
    shipping_weight_g: float | None,
    actual_profit_yen: float | None,
    actual_profit_margin: float | None,
    sold_date: str | None,
    actual_details: dict[str, float | None] | None = None,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    actual_details = actual_details or {}
    if status != STATUS_SOLD:
        with get_connection() as connection:
            current = connection.execute(
                """
                SELECT shipping_carrier,
                       expected_shipping_carrier,
                       shipping_service,
                       expected_shipping_service,
                       shipping_weight_g,
                       package_weight_g,
                       research_shipping_weight_g
                FROM listings
                WHERE id = ?
                """,
                (listing_id,),
            ).fetchone()
        if current is not None:
            shipping_carrier = (
                current["shipping_carrier"]
                or current["expected_shipping_carrier"]
                or None
            )
            shipping_service = (
                current["shipping_service"]
                or current["expected_shipping_service"]
                or None
            )
            shipping_weight_g = (
                current["shipping_weight_g"]
                or current["package_weight_g"]
                or current["research_shipping_weight_g"]
                or None
            )
        actual_sale_price_usd = None
        actual_buyer_shipping_usd = None
        actual_ebay_fee_usd = None
        actual_ad_fee_usd = None
        actual_fixed_fee_usd = None
        effective_ebay_fee_rate = None
        effective_ad_fee_rate = None
        actual_shipping_yen = None
        actual_profit_yen = None
        actual_profit_margin = None
        sold_date = None
        actual_details = {}
    if shipping_carrier == "":
        shipping_carrier = None
    if shipping_service == "":
        shipping_service = None

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE listings
            SET status = ?,
                actual_sale_price_usd = ?,
                actual_sale_price = ?,
                actual_buyer_shipping_usd = ?,
                actual_ebay_fee_usd = ?,
                actual_ad_fee_usd = ?,
                actual_fixed_fee_usd = ?,
                actual_fee_schema_version = ?,
                actual_exchange_rate = ?,
                actual_usd_jpy_rate = ?,
                actual_order_revenue_yen = ?,
                actual_purchase_price_yen = ?,
                actual_overseas_fee_yen = ?,
                actual_copy_cost_yen = ?,
                actual_packaging_yen = ?,
                actual_other_cost_yen = ?,
                actual_base_shipping_yen = ?,
                actual_fuel_surcharge_yen = ?,
                actual_zonos_fee_yen = ?,
                actual_duty_yen = ?,
                actual_additional_fee_yen = ?,
                actual_sales_fee_yen = ?,
                actual_repair_cost_yen = ?,
                actual_parts_cost_yen = ?,
                effective_ebay_fee_rate = ?,
                effective_ad_fee_rate = ?,
                actual_shipping_yen = ?,
                actual_shipping = ?,
                shipping_carrier = ?,
                shipping_service = ?,
                shipping_weight_g = ?,
                actual_profit_yen = ?,
                actual_profit = ?,
                actual_profit_margin = ?,
                sold_date = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                actual_sale_price_usd,
                actual_sale_price_usd,
                actual_buyer_shipping_usd,
                actual_ebay_fee_usd,
                actual_ad_fee_usd,
                actual_fixed_fee_usd,
                ACTUAL_FEE_SCHEMA_SEPARATE,
                actual_details.get("actual_exchange_rate"),
                actual_details.get("actual_usd_jpy_rate"),
                actual_details.get("actual_order_revenue_yen"),
                actual_details.get("actual_purchase_price_yen"),
                actual_details.get("actual_overseas_fee_yen"),
                actual_details.get("actual_copy_cost_yen"),
                actual_details.get("actual_packaging_yen"),
                actual_details.get("actual_other_cost_yen"),
                actual_details.get("actual_base_shipping_yen"),
                actual_details.get("actual_fuel_surcharge_yen"),
                actual_details.get("actual_zonos_fee_yen"),
                actual_details.get("actual_duty_yen"),
                actual_details.get("actual_additional_fee_yen"),
                actual_details.get("actual_sales_fee_yen"),
                actual_details.get("actual_repair_cost_yen"),
                actual_details.get("actual_parts_cost_yen"),
                effective_ebay_fee_rate,
                effective_ad_fee_rate,
                actual_shipping_yen,
                actual_shipping_yen,
                shipping_carrier,
                shipping_service,
                shipping_weight_g,
                actual_profit_yen,
                actual_profit_yen,
                actual_profit_margin,
                sold_date,
                now,
                listing_id,
            ),
        )


def update_listing_details(listing_id: int, updates: dict[str, object]) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = dict(updates)
    expected = calculate_expected_values(row)
    with get_connection() as connection:
        current_source = connection.execute(
            "SELECT * FROM listings WHERE id = ?",
            (listing_id,),
        ).fetchone()
        if current_source is None:
            raise ValueError("更新対象の商品が見つかりません。")
        current = dict(current_source)
        previous_purchase_price = value(
            current,
            "purchase_price_yen",
            "purchase_price",
        )
        stored_actual_purchase = optional_value(
            current,
            "actual_purchase_price_yen",
        )
        actual_purchase_was_inherited = (
            str(current.get("status")) == STATUS_SOLD
            and (
                stored_actual_purchase is None
                or abs(stored_actual_purchase - previous_purchase_price) < 0.005
            )
        )
        connection.execute(
            """
            UPDATE listings
            SET product_name = ?,
                platform = ?,
                currency_code = ?,
                usd_jpy_rate = ?,
                listing_date = ?,
                listing_price_usd = ?,
                listing_price = ?,
                buyer_shipping_usd = ?,
                exchange_rate = ?,
                purchase_price_yen = ?,
                purchase_price = ?,
                domestic_shipping_yen = ?,
                international_shipping_yen = ?,
                packaging_yen = ?,
                other_cost_yen = ?,
                expected_shipping = ?,
                ebay_fee_rate = ?,
                promoted_listing_rate = ?,
                exchange_spread_rate = ?,
                fixed_fee_usd = ?,
                target_profit_yen = ?,
                sales_fee_input_mode = ?,
                sales_fee_rate = ?,
                sales_fee_yen = ?,
                simple_shipping_yen = ?,
                repair_cost_yen = ?,
                parts_cost_yen = ?,
                iphone_model = ?,
                iphone_capacity = ?,
                platform_memo = ?,
                research_memo = ?,
                ebay_fee_yen = ?,
                ad_fee_yen = ?,
                expected_profit_yen = ?,
                profit_yen = ?,
                profit_margin = ?,
                roi = ?,
                gross_sales_yen = ?,
                break_even_sale_price_usd = ?,
                target_sale_price_usd = ?,
                calculated_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                row["product_name"],
                row["platform"],
                row.get("currency_code", DEFAULT_CURRENCY),
                row.get("usd_jpy_rate", 0.0),
                row["listing_date"],
                row["listing_price_usd"],
                row["listing_price_usd"],
                row["buyer_shipping_usd"],
                row["exchange_rate"],
                row["purchase_price_yen"],
                row["purchase_price_yen"],
                row["domestic_shipping_yen"],
                row["international_shipping_yen"],
                row["packaging_yen"],
                row["other_cost_yen"],
                row["international_shipping_yen"],
                row["ebay_fee_rate"],
                row["promoted_listing_rate"],
                row["exchange_spread_rate"],
                row["fixed_fee_usd"],
                row["target_profit_yen"],
                row.get("sales_fee_input_mode", FEE_MODE_RATE),
                row.get("sales_fee_rate", 0.0),
                expected["ebay_fee_yen"]
                if is_simple_profit_platform(row)
                else row.get("sales_fee_yen", 0.0),
                row.get("simple_shipping_yen", 0.0),
                row.get("repair_cost_yen", 0.0),
                row.get("parts_cost_yen", 0.0),
                row.get("iphone_model", ""),
                row.get("iphone_capacity", ""),
                row.get("platform_memo", ""),
                row.get("platform_memo", row.get("research_memo", "")),
                expected["ebay_fee_yen"],
                expected["ad_fee_yen"],
                expected["expected_profit_yen"],
                expected["profit_yen"],
                expected["profit_margin"],
                expected["roi"],
                expected["gross_sales_yen"],
                expected["break_even_sale_price_usd"],
                expected["target_sale_price_usd"],
                now,
                now,
                listing_id,
            ),
        )
        if str(current.get("status")) == STATUS_SOLD:
            latest_source = connection.execute(
                "SELECT * FROM listings WHERE id = ?",
                (listing_id,),
            ).fetchone()
            if latest_source is None:
                raise ValueError("更新後の商品データを取得できませんでした。")
            latest = dict(latest_source)
            latest_rate = (
                optional_value(latest, "actual_exchange_rate")
                or value(latest, "exchange_rate")
                or read_shared_exchange_rate()
                or 1.0
            )
            actual = actual_fee_defaults(latest, latest_rate)
            actual_details = actual_detail_defaults(
                latest,
                latest_rate,
                actual["actual_sale_price_usd"],
                actual["actual_buyer_shipping_usd"],
                actual["actual_shipping_yen"],
            )
            if actual_purchase_was_inherited:
                actual_details["actual_purchase_price_yen"] = float(
                    row["purchase_price_yen"]
                )
            fee_exchange_rate = actual_usd_jpy_rate(latest)
            order_revenue = None
            if not is_simple_profit_platform(latest):
                order_revenue = calculate_order_revenue_yen(
                    float(actual_details["actual_exchange_rate"]),
                    actual["actual_sale_price_usd"],
                    actual["actual_buyer_shipping_usd"],
                    actual["actual_ebay_fee_usd"],
                    actual["actual_ad_fee_usd"],
                    actual["actual_fixed_fee_usd"],
                    fee_exchange_rate,
                )
            actual_profit = calculate_actual_profit(
                latest,
                float(actual_details["actual_exchange_rate"]),
                actual["actual_sale_price_usd"],
                actual["actual_buyer_shipping_usd"],
                actual["actual_ebay_fee_usd"],
                actual["actual_ad_fee_usd"],
                actual["actual_fixed_fee_usd"],
                fee_exchange_rate,
                actual["actual_shipping_yen"],
                actual_details,
            )
            actual_margin = calculate_actual_profit_margin(
                latest,
                actual_profit,
                actual["actual_sale_price_usd"],
                actual["actual_buyer_shipping_usd"],
                actual_details["actual_exchange_rate"],
            )
            connection.execute(
                """
                UPDATE listings
                SET actual_purchase_price_yen = ?,
                    actual_usd_jpy_rate = ?,
                    actual_order_revenue_yen = ?,
                    actual_profit_yen = ?,
                    actual_profit = ?,
                    actual_profit_margin = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    actual_details["actual_purchase_price_yen"],
                    fee_exchange_rate if not is_simple_profit_platform(latest) else None,
                    order_revenue,
                    actual_profit,
                    actual_profit,
                    actual_margin,
                    now,
                    listing_id,
                ),
            )

        saved = connection.execute(
            """
            SELECT purchase_price_yen, purchase_price,
                   expected_profit_yen, profit_yen, profit_margin
            FROM listings
            WHERE id = ?
            """,
            (listing_id,),
        ).fetchone()
        if saved is None:
            raise ValueError("保存した商品データを確認できませんでした。")
        expected_purchase = float(row["purchase_price_yen"])
        if (
            abs(float(saved["purchase_price_yen"]) - expected_purchase) >= 0.005
            or abs(float(saved["purchase_price"]) - expected_purchase) >= 0.005
        ):
            raise RuntimeError("仕入れ価格をデータベースへ保存できませんでした。")
        if (
            abs(
                float(saved["expected_profit_yen"])
                - float(expected["expected_profit_yen"] or 0)
            )
            >= 0.005
            or abs(
                float(saved["profit_yen"])
                - float(expected["profit_yen"] or 0)
            )
            >= 0.005
            or abs(
                float(saved["profit_margin"])
                - float(expected["profit_margin"] or 0)
            )
            >= 0.005
        ):
            raise RuntimeError("仕入れ価格変更後の利益を保存できませんでした。")


def duplicate_listing(listing_id: int) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = date.today().isoformat()
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM listings WHERE id = ?",
            (listing_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Listing was not found")

        data = dict(row)
        data["listing_date"] = today
        data["status"] = STATUS_ACTIVE
        data["sold_date"] = None
        data["actual_sale_price_usd"] = None
        data["actual_sale_price"] = None
        data["actual_buyer_shipping_usd"] = None
        data["actual_ebay_fee_usd"] = None
        data["actual_ad_fee_usd"] = None
        data["actual_fixed_fee_usd"] = None
        data["actual_fee_schema_version"] = ACTUAL_FEE_SCHEMA_SEPARATE
        data["actual_exchange_rate"] = None
        data["actual_usd_jpy_rate"] = None
        data["actual_order_revenue_yen"] = None
        data["actual_purchase_price_yen"] = None
        data["actual_overseas_fee_yen"] = None
        data["actual_copy_cost_yen"] = None
        data["actual_packaging_yen"] = None
        data["actual_other_cost_yen"] = None
        data["actual_base_shipping_yen"] = None
        data["actual_fuel_surcharge_yen"] = None
        data["actual_zonos_fee_yen"] = None
        data["actual_duty_yen"] = None
        data["actual_additional_fee_yen"] = None
        data["actual_sales_fee_yen"] = None
        data["actual_repair_cost_yen"] = None
        data["actual_parts_cost_yen"] = None
        data["effective_ebay_fee_rate"] = None
        data["effective_ad_fee_rate"] = None
        data["actual_shipping_yen"] = None
        data["actual_shipping"] = None
        data["shipping_carrier"] = data.get("expected_shipping_carrier") or None
        data["shipping_service"] = data.get("expected_shipping_service") or None
        data["shipping_weight_g"] = (
            data.get("package_weight_g")
            or data.get("research_shipping_weight_g")
            or None
        )
        data["actual_profit_yen"] = None
        data["actual_profit"] = None
        data["actual_profit_margin"] = None
        data["calculated_at"] = now
        data["created_at"] = now
        data["updated_at"] = now

        columns = [column for column in data.keys() if column != "id"]
        placeholders = ", ".join("?" for _ in columns)
        column_list = ", ".join(columns)
        cursor = connection.execute(
            f"INSERT INTO listings ({column_list}) VALUES ({placeholders})",
            tuple(data[column] for column in columns),
        )
        return int(cursor.lastrowid)


def delete_listing(listing_id: int) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM listings WHERE id = ?", (listing_id,))


def normalize_row(row: dict[str, object]) -> dict[str, object]:
    result = dict(row)
    result["platform"] = platform_value(row)
    result["currency_code"] = (
        "JPY" if is_simple_profit_platform(row) else listing_currency(row)
    )
    result["sale_price_usd"] = value(row, "listing_price_usd", "listing_price")
    result["purchase_price_yen"] = value(row, "purchase_price_yen", "purchase_price")
    result["international_shipping_yen"] = value(
        row,
        "international_shipping_yen",
        "expected_shipping",
    )
    result["other_cost_yen"] = value(row, "other_cost_yen")
    result["target_profit_yen"] = value(row, "target_profit_yen")
    result["profit_yen"] = value(row, "profit_yen", "expected_profit_yen")
    result["actual_sale_price_usd"] = optional_value(row, "actual_sale_price_usd")
    if result["actual_sale_price_usd"] is None:
        result["actual_sale_price_usd"] = optional_value(row, "actual_sale_price")
    result["actual_buyer_shipping_usd"] = optional_value(row, "actual_buyer_shipping_usd")
    result["actual_ebay_fee_usd"] = optional_value(row, "actual_ebay_fee_usd")
    result["actual_ad_fee_usd"] = optional_value(row, "actual_ad_fee_usd")
    result["actual_fixed_fee_usd"] = optional_value(row, "actual_fixed_fee_usd")
    result["actual_fee_schema_version"] = actual_fee_schema_version(row)
    result["actual_exchange_rate"] = optional_value(row, "actual_exchange_rate")
    result["actual_usd_jpy_rate"] = optional_value(row, "actual_usd_jpy_rate")
    result["actual_order_revenue_yen"] = optional_value(
        row,
        "actual_order_revenue_yen",
    )
    result["actual_purchase_price_yen"] = optional_value(row, "actual_purchase_price_yen")
    result["actual_overseas_fee_yen"] = optional_value(row, "actual_overseas_fee_yen")
    result["actual_copy_cost_yen"] = optional_value(row, "actual_copy_cost_yen")
    result["actual_packaging_yen"] = optional_value(row, "actual_packaging_yen")
    result["actual_other_cost_yen"] = optional_value(row, "actual_other_cost_yen")
    result["actual_base_shipping_yen"] = optional_value(row, "actual_base_shipping_yen")
    result["actual_fuel_surcharge_yen"] = optional_value(row, "actual_fuel_surcharge_yen")
    result["actual_zonos_fee_yen"] = optional_value(row, "actual_zonos_fee_yen")
    result["actual_duty_yen"] = optional_value(row, "actual_duty_yen")
    result["actual_additional_fee_yen"] = optional_value(row, "actual_additional_fee_yen")
    result["effective_ebay_fee_rate"] = optional_value(row, "effective_ebay_fee_rate")
    result["effective_ad_fee_rate"] = optional_value(row, "effective_ad_fee_rate")
    result["actual_shipping_yen"] = optional_value(row, "actual_shipping_yen")
    if result["actual_shipping_yen"] is None:
        result["actual_shipping_yen"] = optional_value(row, "actual_shipping")
    result["shipping_carrier"] = str(row.get("shipping_carrier") or "")
    result["shipping_service"] = str(row.get("shipping_service") or "")
    result["shipping_weight_g"] = optional_value(row, "shipping_weight_g")
    result["actual_profit_yen"] = optional_value(row, "actual_profit_yen")
    if result["actual_profit_yen"] is None:
        result["actual_profit_yen"] = optional_value(row, "actual_profit")
    result["actual_profit_margin"] = optional_value(row, "actual_profit_margin")
    result["sku"] = str(row.get("sku") or "")
    result["source_url"] = str(row.get("source_url") or "")
    result["destination_country"] = str(row.get("destination_country") or "")
    result["sale_price_yen"] = value(row, "sale_price_yen")
    result["package_weight_g"] = value(row, "package_weight_g")
    result["package_length_cm"] = value(row, "package_length_cm")
    result["package_width_cm"] = value(row, "package_width_cm")
    result["package_height_cm"] = value(row, "package_height_cm")
    result["expected_shipping_carrier"] = str(row.get("expected_shipping_carrier") or "")
    result["expected_shipping_service"] = str(row.get("expected_shipping_service") or "")
    result["planned_shipping_yen"] = value(row, "planned_shipping_yen")
    result["planned_profit_margin"] = value(row, "planned_profit_margin")
    result["planned_base_shipping_yen"] = value(row, "planned_base_shipping_yen")
    result["planned_fuel_surcharge_yen"] = value(row, "planned_fuel_surcharge_yen")
    result["planned_additional_fee_yen"] = value(row, "planned_additional_fee_yen")
    result["planned_shipping_status"] = str(row.get("planned_shipping_status") or "")
    result["planned_shipping_reason"] = str(row.get("planned_shipping_reason") or "")
    result["rate_table_weight_g"] = optional_value(row, "rate_table_weight_g")
    result["shipping_breakdown_json"] = str(row.get("shipping_breakdown_json") or "")
    result["overseas_fee_rate"] = value(row, "overseas_fee_rate")
    result["overseas_fee_yen"] = value(row, "overseas_fee_yen")
    result["other_fee_yen"] = value(row, "other_fee_yen")
    result["shipping_calculation_mode"] = str(row.get("shipping_calculation_mode") or "")
    result["volumetric_weight_g"] = optional_value(row, "volumetric_weight_g")
    result["applied_weight_g"] = optional_value(row, "applied_weight_g")
    result["billing_weight_g"] = optional_value(row, "billing_weight_g")
    result["zonos_applied"] = value(row, "zonos_applied")
    result["zonos_base_shipping_yen"] = value(row, "zonos_base_shipping_yen")
    result["zonos_fee_base_yen"] = value(row, "zonos_fee_base_yen")
    result["zonos_fee_rate_percent"] = value(row, "zonos_fee_rate_percent")
    result["zonos_fee_yen"] = value(row, "zonos_fee_yen")
    result["zonos_duty_rate_percent"] = value(row, "zonos_duty_rate_percent")
    result["zonos_duty_base_yen"] = value(row, "zonos_duty_base_yen")
    result["zonos_duty_yen"] = value(row, "zonos_duty_yen")
    result["zonos_total_shipping_yen"] = value(row, "zonos_total_shipping_yen")
    result["zonos_config_effective_from"] = str(row.get("zonos_config_effective_from") or "")
    result["zonos_config_effective_to"] = str(row.get("zonos_config_effective_to") or "")
    result["registered_at"] = str(row.get("registered_at") or "")
    result["sales_fee_input_mode"] = str(
        row.get("sales_fee_input_mode") or FEE_MODE_RATE
    )
    result["sales_fee_rate"] = value(row, "sales_fee_rate")
    result["sales_fee_yen"] = value(row, "sales_fee_yen")
    result["simple_shipping_yen"] = value(row, "simple_shipping_yen")
    result["repair_cost_yen"] = value(row, "repair_cost_yen")
    result["parts_cost_yen"] = value(row, "parts_cost_yen")
    result["iphone_model"] = str(row.get("iphone_model") or "")
    result["iphone_capacity"] = str(row.get("iphone_capacity") or "")
    result["platform_memo"] = str(
        row.get("platform_memo") or row.get("research_memo") or ""
    )
    result["actual_sales_fee_yen"] = optional_value(
        row,
        "actual_sales_fee_yen",
    )
    result["actual_repair_cost_yen"] = optional_value(
        row,
        "actual_repair_cost_yen",
    )
    result["actual_parts_cost_yen"] = optional_value(
        row,
        "actual_parts_cost_yen",
    )
    return result


def shipping_breakdown_from_row(row: dict[str, object]) -> dict[str, object]:
    raw = str(row.get("shipping_breakdown_json") or "")
    payload: dict[str, object] = {}
    if raw:
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                payload = loaded
        except json.JSONDecodeError:
            pass

    total_yen = float(
        payload.get("total_yen")
        or row.get("planned_shipping_yen")
        or value(row, "international_shipping_yen", "expected_shipping")
        or 0
    )
    items = []
    raw_items = payload.get("items")
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            amount = float(item.get("amount_yen") or 0)
            if round(amount) == 0:
                continue
            items.append({"label": str(item.get("label") or ""), "amount_yen": amount})

    if not items:
        zonos_applied = bool(payload.get("zonos_applied")) or bool(value(row, "zonos_applied"))
        base_shipping_yen = float(
            payload.get("base_shipping_yen")
            or (value(row, "zonos_base_shipping_yen") if zonos_applied else 0)
            or value(row, "planned_base_shipping_yen")
            or 0
        )
        fuel_surcharge_yen = float(
            payload.get("fuel_surcharge_yen")
            or value(row, "planned_fuel_surcharge_yen")
            or 0
        )
        zonos_fee_yen = float(payload.get("zonos_fee_yen") or value(row, "zonos_fee_yen") or 0)
        zonos_duty_yen = float(payload.get("zonos_duty_yen") or value(row, "zonos_duty_yen") or 0)
        additional_total_yen = float(
            payload.get("additional_total_yen")
            or value(row, "planned_additional_fee_yen")
            or 0
        )
        has_component_data = any(
            round(amount) != 0
            for amount in (
                base_shipping_yen,
                fuel_surcharge_yen,
                zonos_fee_yen,
                zonos_duty_yen,
                additional_total_yen,
            )
        )

        def add_item(label: str, amount_yen: float) -> None:
            if round(amount_yen) != 0:
                items.append({"label": label, "amount_yen": amount_yen})

        if has_component_data:
            add_item("日本郵便基本送料" if zonos_applied else "基本送料", base_shipping_yen)
            if zonos_applied:
                add_item(TEXT["zonos_fee_yen"], zonos_fee_yen)
                add_item(TEXT["zonos_duty_yen"], zonos_duty_yen)
            add_item(TEXT["planned_fuel_surcharge_yen"], fuel_surcharge_yen)
            known_total = base_shipping_yen + fuel_surcharge_yen + zonos_fee_yen + zonos_duty_yen + additional_total_yen
            remainder_yen = round(total_yen - known_total)
            add_item(TEXT["planned_additional_fee_yen"], additional_total_yen + remainder_yen)

    return {
        "carrier": payload.get("carrier") or row.get("expected_shipping_carrier") or row.get("shipping_carrier") or "",
        "service": payload.get("service") or row.get("expected_shipping_service") or "",
        "items": items,
        "total_yen": total_yen,
        "has_saved_breakdown": bool(raw),
        "actual_weight_g": payload.get("actual_weight_g") or value(row, "package_weight_g", "research_shipping_weight_g"),
        "volumetric_weight_g": payload.get("volumetric_weight_g") or optional_value(row, "volumetric_weight_g"),
        "billing_weight_g": payload.get("billing_weight_g") or optional_value(row, "billing_weight_g"),
        "rate_table_weight_g": payload.get("rate_table_weight_g") or optional_value(row, "rate_table_weight_g"),
        "status": payload.get("status") or row.get("planned_shipping_status") or "",
        "reason": payload.get("reason") or row.get("planned_shipping_reason") or "",
        "destination_country": payload.get("destination_country") or row.get("destination_country") or "",
        "calculated_at": payload.get("calculated_at") or row.get("calculated_at") or "",
    }


def render_shipping_breakdown(row: dict[str, object]) -> None:
    payload = shipping_breakdown_from_row(row)
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    carrier = str(payload.get("carrier") or row.get("expected_shipping_carrier") or "")
    service = str(payload.get("service") or row.get("expected_shipping_service") or "")
    with st.expander("送料内訳を見る", expanded=False):
        st.markdown("**送料内訳**")
        st.write("配送方法")
        st.markdown(f"**{carrier} {service}**".strip())
        if not items:
            st.info("この商品には送料内訳データが保存されていません。")
        for item in items:
            if not isinstance(item, dict):
                continue
            amount = float(item.get("amount_yen") or 0)
            if amount == 0:
                continue
            line_col1, line_col2 = st.columns([2, 1])
            line_col1.write(str(item.get("label") or ""))
            line_col2.write(yen(amount))
        st.divider()
        total_yen = float(payload.get("total_yen") or 0)
        st.markdown(f"### 合計送料　{yen(total_yen)}")
        saved_total = value(row, "international_shipping_yen", "expected_shipping")
        if round(total_yen) != round(saved_total):
            st.warning(
                f"内訳の合計送料と海外送料が異なるため、利益計算時に保存された合計送料 {yen(total_yen)} を表示しています。"
            )
        weight_cols = st.columns(4)
        weight_cols[0].metric("実重量(g)", display_value(payload.get("actual_weight_g")))
        weight_cols[1].metric("容積重量(g)", display_value(payload.get("volumetric_weight_g")))
        weight_cols[2].metric("請求重量(g)", display_value(payload.get("billing_weight_g")))
        weight_cols[3].metric("料金重量(g)", display_value(payload.get("rate_table_weight_g")))
        status = str(payload.get("status") or "")
        reason = str(payload.get("reason") or "")
        destination = str(payload.get("destination_country") or row.get("destination_country") or "")
        st.caption(f"配送先: {destination} / 発送可否: {status or '-'} / 理由: {reason or '-'}")
        calculated_at = str(payload.get("calculated_at") or "")
        if calculated_at:
            st.caption(f"計算日時: {calculated_at}")


def format_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    formatted = []
    for source in rows:
        row = normalize_row(source)
        formatted.append(
            {
                DISPLAY_COLUMNS["id"]: row["id"],
                DISPLAY_COLUMNS["product_name"]: row["product_name"],
                DISPLAY_COLUMNS["platform"]: row["platform"],
                DISPLAY_COLUMNS["currency_code"]: row.get("currency_code", DEFAULT_CURRENCY),
                DISPLAY_COLUMNS["listing_date"]: row.get("listing_date", ""),
                DISPLAY_COLUMNS["sale_price_usd"]: row["sale_price_usd"],
                DISPLAY_COLUMNS["buyer_shipping_usd"]: row.get("buyer_shipping_usd", 0),
                DISPLAY_COLUMNS["exchange_rate"]: row.get("exchange_rate", 0),
                DISPLAY_COLUMNS["usd_jpy_rate"]: row.get("usd_jpy_rate", 0),
                DISPLAY_COLUMNS["purchase_price_yen"]: row["purchase_price_yen"],
                DISPLAY_COLUMNS["domestic_shipping_yen"]: row.get("domestic_shipping_yen", 0),
                DISPLAY_COLUMNS["international_shipping_yen"]: row["international_shipping_yen"],
                DISPLAY_COLUMNS["packaging_yen"]: row.get("packaging_yen", 0),
                DISPLAY_COLUMNS["other_cost_yen"]: row["other_cost_yen"],
                DISPLAY_COLUMNS["ebay_fee_rate"]: row.get("ebay_fee_rate", 0),
                DISPLAY_COLUMNS["promoted_listing_rate"]: row.get("promoted_listing_rate", 0),
                DISPLAY_COLUMNS["exchange_spread_rate"]: row.get("exchange_spread_rate", 0),
                DISPLAY_COLUMNS["fixed_fee_usd"]: row.get("fixed_fee_usd", 0),
                DISPLAY_COLUMNS["target_profit_yen"]: row["target_profit_yen"],
                DISPLAY_COLUMNS["profit_yen"]: row["profit_yen"],
                DISPLAY_COLUMNS["profit_margin"]: row.get("profit_margin", 0),
                DISPLAY_COLUMNS["roi"]: row.get("roi", ""),
                DISPLAY_COLUMNS["gross_sales_yen"]: row.get("gross_sales_yen", 0),
                DISPLAY_COLUMNS["break_even_sale_price_usd"]: row.get("break_even_sale_price_usd", ""),
                DISPLAY_COLUMNS["target_sale_price_usd"]: row.get("target_sale_price_usd", ""),
                DISPLAY_COLUMNS["search_keyword"]: row.get("search_keyword", ""),
                DISPLAY_COLUMNS["monthly_sales"]: row.get("monthly_sales", 0),
                DISPLAY_COLUMNS["competitor_count"]: row.get("competitor_count", 0),
                DISPLAY_COLUMNS["product_url"]: row.get("product_url", ""),
                DISPLAY_COLUMNS["research_shipping_weight_g"]: row.get("research_shipping_weight_g", 0),
                DISPLAY_COLUMNS["inventory_risk"]: row.get("inventory_risk", ""),
                DISPLAY_COLUMNS["research_memo"]: row.get("research_memo", ""),
                DISPLAY_COLUMNS["sku"]: row.get("sku", ""),
                DISPLAY_COLUMNS["source_url"]: row.get("source_url", ""),
                DISPLAY_COLUMNS["destination_country"]: row.get("destination_country", ""),
                DISPLAY_COLUMNS["sale_price_yen"]: row.get("sale_price_yen", 0),
                DISPLAY_COLUMNS["package_weight_g"]: row.get("package_weight_g", 0),
                DISPLAY_COLUMNS["package_length_cm"]: row.get("package_length_cm", 0),
                DISPLAY_COLUMNS["package_width_cm"]: row.get("package_width_cm", 0),
                DISPLAY_COLUMNS["package_height_cm"]: row.get("package_height_cm", 0),
                DISPLAY_COLUMNS["expected_shipping_carrier"]: row.get("expected_shipping_carrier", ""),
                DISPLAY_COLUMNS["expected_shipping_service"]: row.get("expected_shipping_service", ""),
                DISPLAY_COLUMNS["planned_shipping_yen"]: row.get("planned_shipping_yen", 0),
                DISPLAY_COLUMNS["planned_profit_margin"]: row.get("planned_profit_margin", 0),
                DISPLAY_COLUMNS["planned_base_shipping_yen"]: row.get("planned_base_shipping_yen", 0),
                DISPLAY_COLUMNS["planned_fuel_surcharge_yen"]: row.get("planned_fuel_surcharge_yen", 0),
                DISPLAY_COLUMNS["planned_additional_fee_yen"]: row.get("planned_additional_fee_yen", 0),
                DISPLAY_COLUMNS["planned_shipping_status"]: row.get("planned_shipping_status", ""),
                DISPLAY_COLUMNS["planned_shipping_reason"]: row.get("planned_shipping_reason", ""),
                DISPLAY_COLUMNS["rate_table_weight_g"]: display_value(row.get("rate_table_weight_g")),
                DISPLAY_COLUMNS["overseas_fee_rate"]: row.get("overseas_fee_rate", 0),
                DISPLAY_COLUMNS["overseas_fee_yen"]: row.get("overseas_fee_yen", 0),
                DISPLAY_COLUMNS["other_fee_yen"]: row.get("other_fee_yen", 0),
                DISPLAY_COLUMNS["shipping_calculation_mode"]: row.get("shipping_calculation_mode", ""),
                DISPLAY_COLUMNS["volumetric_weight_g"]: display_value(row.get("volumetric_weight_g")),
                DISPLAY_COLUMNS["applied_weight_g"]: display_value(row.get("applied_weight_g")),
                DISPLAY_COLUMNS["billing_weight_g"]: display_value(row.get("billing_weight_g")),
                DISPLAY_COLUMNS["zonos_applied"]: "あり" if value(row, "zonos_applied") else "",
                DISPLAY_COLUMNS["zonos_base_shipping_yen"]: row.get("zonos_base_shipping_yen", 0),
                DISPLAY_COLUMNS["zonos_fee_base_yen"]: row.get("zonos_fee_base_yen", 0),
                DISPLAY_COLUMNS["zonos_fee_rate_percent"]: row.get("zonos_fee_rate_percent", 0),
                DISPLAY_COLUMNS["zonos_fee_yen"]: row.get("zonos_fee_yen", 0),
                DISPLAY_COLUMNS["zonos_duty_rate_percent"]: row.get("zonos_duty_rate_percent", 0),
                DISPLAY_COLUMNS["zonos_duty_base_yen"]: row.get("zonos_duty_base_yen", 0),
                DISPLAY_COLUMNS["zonos_duty_yen"]: row.get("zonos_duty_yen", 0),
                DISPLAY_COLUMNS["zonos_total_shipping_yen"]: row.get("zonos_total_shipping_yen", 0),
                DISPLAY_COLUMNS["zonos_config_effective_from"]: row.get("zonos_config_effective_from", ""),
                DISPLAY_COLUMNS["zonos_config_effective_to"]: row.get("zonos_config_effective_to", ""),
                DISPLAY_COLUMNS["registered_at"]: row.get("registered_at", ""),
                DISPLAY_COLUMNS["sales_fee_input_mode"]: row.get("sales_fee_input_mode", ""),
                DISPLAY_COLUMNS["sales_fee_rate"]: row.get("sales_fee_rate", 0),
                DISPLAY_COLUMNS["sales_fee_yen"]: row.get("sales_fee_yen", 0),
                DISPLAY_COLUMNS["simple_shipping_yen"]: row.get("simple_shipping_yen", 0),
                DISPLAY_COLUMNS["repair_cost_yen"]: row.get("repair_cost_yen", 0),
                DISPLAY_COLUMNS["parts_cost_yen"]: row.get("parts_cost_yen", 0),
                DISPLAY_COLUMNS["iphone_model"]: row.get("iphone_model", ""),
                DISPLAY_COLUMNS["iphone_capacity"]: row.get("iphone_capacity", ""),
                DISPLAY_COLUMNS["platform_memo"]: row.get("platform_memo", ""),
                DISPLAY_COLUMNS["calculated_at"]: row.get("calculated_at", ""),
                DISPLAY_COLUMNS["status"]: row.get("status", ""),
                DISPLAY_COLUMNS["sold_date"]: row.get("sold_date", "") or "",
                DISPLAY_COLUMNS["actual_sale_price_usd"]: display_value(row["actual_sale_price_usd"]),
                DISPLAY_COLUMNS["actual_buyer_shipping_usd"]: display_value(row["actual_buyer_shipping_usd"]),
                DISPLAY_COLUMNS["actual_ebay_fee_usd"]: display_value(row["actual_ebay_fee_usd"]),
                DISPLAY_COLUMNS["actual_ad_fee_usd"]: display_value(row["actual_ad_fee_usd"]),
                DISPLAY_COLUMNS["actual_fixed_fee_usd"]: display_value(row["actual_fixed_fee_usd"]),
                DISPLAY_COLUMNS["actual_exchange_rate"]: display_value(row["actual_exchange_rate"]),
                DISPLAY_COLUMNS["actual_usd_jpy_rate"]: display_value(row["actual_usd_jpy_rate"]),
                DISPLAY_COLUMNS["actual_order_revenue_yen"]: display_value(row["actual_order_revenue_yen"]),
                DISPLAY_COLUMNS["effective_ebay_fee_rate"]: display_value(row["effective_ebay_fee_rate"]),
                DISPLAY_COLUMNS["effective_ad_fee_rate"]: display_value(row["effective_ad_fee_rate"]),
                DISPLAY_COLUMNS["actual_shipping_yen"]: display_value(row["actual_shipping_yen"]),
                DISPLAY_COLUMNS["shipping_carrier"]: display_value(row["shipping_carrier"]),
                DISPLAY_COLUMNS["shipping_weight_g"]: display_value(row["shipping_weight_g"]),
                DISPLAY_COLUMNS["actual_profit_yen"]: display_value(row["actual_profit_yen"]),
            }
        )
    return formatted


def format_summary_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    formatted = []
    for source in rows:
        row = normalize_row(source)
        formatted.append(
            {
                "ID": row["id"],
                TEXT["product_name"]: row["product_name"],
                TEXT["platform"]: row["platform"],
                TEXT["status"]: row.get("status", ""),
                TEXT["listing_date"]: row.get("listing_date", ""),
                TEXT["profit_yen"]: row["profit_yen"],
                TEXT["actual_profit_yen"]: display_value(row["actual_profit_yen"]),
                TEXT["shipping_carrier"]: display_value(row["shipping_carrier"]),
                TEXT["shipping_weight_g"]: display_value(row["shipping_weight_g"]),
                TEXT["sold_date"]: row.get("sold_date", "") or "",
            }
        )
    return formatted


def keep_summary_section(section_key: str, listing_id: int | None = None, scroll: bool = False) -> None:
    if section_key not in SUMMARY_SECTION_STATUSES:
        return
    st.session_state.current_section = section_key
    for candidate in SUMMARY_SECTION_STATUSES:
        st.session_state[f"summary_expanded_{candidate}"] = candidate == section_key
    if listing_id is not None:
        st.session_state.selected_listing_id = listing_id
        st.session_state.editing_listing_id = listing_id
    if scroll:
        st.session_state.scroll_to_summary_section = section_key


def keep_summary_section_for_status(status: str, listing_id: int | None = None, scroll: bool = False) -> None:
    keep_summary_section(SUMMARY_SECTIONS.get(status, "active"), listing_id, scroll)


def close_management_editor_after_update(status: str) -> None:
    keep_summary_section_for_status(status, None, scroll=True)
    for key in (
        "selected_listing_id",
        "editing_listing_id",
        "focus_listing_id",
        "scroll_to_listing_id",
        "duplicated_listing_id",
    ):
        st.session_state.pop(key, None)


def select_listing_for_edit(listing_id: int, section_key: str | None = None) -> None:
    if section_key:
        keep_summary_section(section_key, listing_id, scroll=False)
    st.session_state.selected_listing_id = listing_id
    st.session_state.editing_listing_id = listing_id
    st.session_state.focus_listing_id = listing_id
    st.session_state.scroll_to_listing_id = listing_id
    st.rerun()


def apply_listing_query_params(rows: list[dict[str, object]]) -> None:
    try:
        raw_listing_id = st.query_params.get("edit_listing_id")
        raw_section = st.query_params.get("edit_section")
        raw_click_token = st.query_params.get("edit_click")
    except AttributeError:
        return
    if isinstance(raw_listing_id, list):
        raw_listing_id = raw_listing_id[0] if raw_listing_id else None
    if isinstance(raw_section, list):
        raw_section = raw_section[0] if raw_section else None
    if isinstance(raw_click_token, list):
        raw_click_token = raw_click_token[0] if raw_click_token else None
    if raw_listing_id in (None, ""):
        return

    try:
        listing_id = int(raw_listing_id)
    except (TypeError, ValueError):
        return
    if listing_id not in {int(row["id"]) for row in rows}:
        return

    query_key = f"{listing_id}:{raw_click_token or ''}"
    if st.session_state.get("last_query_listing_key") != query_key:
        st.session_state.selected_listing_id = listing_id
        st.session_state.editing_listing_id = listing_id
        st.session_state.focus_listing_id = listing_id
        if raw_section in SUMMARY_SECTION_STATUSES:
            keep_summary_section(str(raw_section), listing_id, scroll=False)
        st.session_state.scroll_to_listing_id = listing_id
        st.session_state.last_query_listing_key = query_key


def clear_mobile_delete_query_params() -> None:
    try:
        for key in (
            "mobile_delete_listing_id",
            "mobile_delete_section",
            "mobile_delete_click",
        ):
            if key in st.query_params:
                del st.query_params[key]
    except AttributeError:
        pass


def apply_mobile_delete_query_params(rows: list[dict[str, object]]) -> None:
    try:
        raw_listing_id = st.query_params.get("mobile_delete_listing_id")
        raw_section = st.query_params.get("mobile_delete_section")
        raw_click_token = st.query_params.get("mobile_delete_click")
    except AttributeError:
        return
    if isinstance(raw_listing_id, list):
        raw_listing_id = raw_listing_id[0] if raw_listing_id else None
    if isinstance(raw_section, list):
        raw_section = raw_section[0] if raw_section else None
    if isinstance(raw_click_token, list):
        raw_click_token = raw_click_token[0] if raw_click_token else None
    if raw_listing_id in (None, ""):
        return
    try:
        listing_id = int(raw_listing_id)
    except (TypeError, ValueError):
        return
    if listing_id not in {int(row["id"]) for row in rows}:
        return

    query_key = f"{listing_id}:{raw_click_token or ''}"
    if st.session_state.get("last_mobile_delete_query_key") == query_key:
        return
    st.session_state.pending_mobile_delete_listing_id = listing_id
    st.session_state.last_mobile_delete_query_key = query_key
    if raw_section in SUMMARY_SECTION_STATUSES:
        keep_summary_section(str(raw_section), listing_id, scroll=True)


def render_mobile_delete_confirmation(rows: list[dict[str, object]]) -> None:
    pending_id = st.session_state.get("pending_mobile_delete_listing_id")
    if pending_id is None:
        return
    target = next(
        (row for row in rows if int(row["id"]) == int(pending_id)),
        None,
    )
    if target is None:
        st.session_state.pop("pending_mobile_delete_listing_id", None)
        clear_mobile_delete_query_params()
        return

    st.warning(
        f"「{target.get('product_name', '')}」を削除しますか？"
        "この操作は元に戻せません。"
    )
    confirm_col, cancel_col = st.columns(2)
    if confirm_col.button(
        "削除を確定",
        type="primary",
        key=f"confirm_mobile_delete_{pending_id}",
    ):
        delete_listing(int(pending_id))
        for key in (
            "pending_mobile_delete_listing_id",
            "selected_listing_id",
            "editing_listing_id",
            "focus_listing_id",
        ):
            if key == "pending_mobile_delete_listing_id" or (
                st.session_state.get(key) == int(pending_id)
            ):
                st.session_state.pop(key, None)
        clear_mobile_delete_query_params()
        st.success(TEXT["deleted"])
        st.rerun()
    if cancel_col.button(
        "キャンセル",
        key=f"cancel_mobile_delete_{pending_id}",
    ):
        st.session_state.pop("pending_mobile_delete_listing_id", None)
        clear_mobile_delete_query_params()
        st.rerun()


def scroll_to_management_editor() -> None:
    components.html(
        """
        <script>
        const target = window.parent.document.getElementById("management-editor");
        if (target) {
            target.scrollIntoView({ behavior: "smooth", block: "start" });
        }
        </script>
        """,
        height=0,
    )


def scroll_to_summary_section(section_key: str) -> None:
    components.html(
        f"""
        <script>
        const scrollToSummary = () => {{
            const target = window.parent.document.getElementById("summary-section-{section_key}");
            if (target) {{
                target.scrollIntoView({{ behavior: "smooth", block: "start" }});
            }}
        }};
        window.setTimeout(scrollToSummary, 50);
        window.setTimeout(scrollToSummary, 250);
        window.setTimeout(scrollToSummary, 600);
        window.setTimeout(scrollToSummary, 1000);
        </script>
        """,
        height=0,
    )


def date_ordinal(value_text: object) -> int:
    try:
        return date.fromisoformat(str(value_text or "")).toordinal()
    except ValueError:
        return 0


def sort_summary_rows(
    rows: list[dict[str, object]],
    sort_column: str,
    sort_direction: str,
) -> list[dict[str, object]]:
    normalized_rows = [normalize_row(row) for row in rows]
    reverse = sort_direction == "desc"
    if sort_column == "profit_yen":
        key_func = lambda row: (value(row, "profit_yen"), int(row["id"]))
    elif sort_column == "actual_profit_yen":
        key_func = lambda row: (value(row, "actual_profit_yen", "actual_profit"), int(row["id"]))
    elif sort_column == "sold_date":
        key_func = lambda row: (date_ordinal(row.get("sold_date")), int(row["id"]))
    else:
        key_func = lambda row: (date_ordinal(row.get("listing_date")), int(row["id"]))
    return sorted(
        normalized_rows,
        key=key_func,
        reverse=reverse,
    )


def apply_summary_sort_query_params() -> None:
    try:
        raw_section = st.query_params.get("summary_sort_section")
        raw_status = st.query_params.get("summary_sort_status")
        raw_column = st.query_params.get("summary_sort_column")
        raw_direction = st.query_params.get("summary_sort_direction")
        raw_click_token = st.query_params.get("summary_sort_click")
    except AttributeError:
        return

    if isinstance(raw_section, list):
        raw_section = raw_section[0] if raw_section else None
    if isinstance(raw_status, list):
        raw_status = raw_status[0] if raw_status else None
    if isinstance(raw_column, list):
        raw_column = raw_column[0] if raw_column else None
    if isinstance(raw_direction, list):
        raw_direction = raw_direction[0] if raw_direction else None
    if isinstance(raw_click_token, list):
        raw_click_token = raw_click_token[0] if raw_click_token else None

    if raw_section in SUMMARY_SECTION_STATUSES:
        section_key = str(raw_section)
        status = SUMMARY_SECTION_STATUSES[section_key]
    elif raw_status in STATUS_OPTIONS:
        status = str(raw_status)
        section_key = SUMMARY_SECTIONS[status]
    else:
        return
    if raw_column not in ("profit_yen", "actual_profit_yen", "listing_date", "sold_date"):
        return
    if raw_direction not in ("asc", "desc"):
        return

    query_key = f"{section_key}:{raw_column}:{raw_direction}:{raw_click_token or ''}"
    if st.session_state.get("last_summary_sort_query_key") == query_key:
        return
    st.session_state.current_section = section_key
    for candidate in SUMMARY_SECTION_STATUSES:
        st.session_state[f"summary_expanded_{candidate}"] = candidate == section_key
    st.session_state[f"sort_column_{section_key}"] = raw_column
    st.session_state[f"sort_order_{section_key}"] = raw_direction
    st.session_state.last_summary_sort_query_key = query_key
    st.session_state.scroll_to_summary_section = section_key


def filter_rows_by_platform(rows: list[dict[str, object]], platform_filter: str) -> list[dict[str, object]]:
    if platform_filter == PLATFORM_ALL:
        return rows
    return [row for row in rows if platform_value(row) == platform_filter]


def build_mobile_listing_cards(
    rows: list[dict[str, object]],
    click_token: str,
) -> str:
    cards: list[str] = []
    for source in rows:
        row = normalize_row(source)
        listing_id = int(row["id"])
        platform = platform_value(row)
        status = str(row.get("status") or STATUS_ACTIVE)
        section_key = SUMMARY_SECTIONS.get(status, "active")
        price_value = value(row, "listing_price_usd", "listing_price")
        if is_simple_profit_platform(row):
            price_label = (
                "売却価格"
                if platform == PLATFORM_IPHONE_RESALE
                else "販売価格"
            )
            price_text = yen(price_value)
        else:
            currency_code = listing_currency(row)
            price_label = f"販売価格（{currency_code}）"
            price_text = f"{currency_symbol(currency_code)}{price_value:,.2f}"
        profit_value = value(row, "profit_yen", "expected_profit_yen")
        profit_class = "positive" if profit_value >= 0 else "negative"
        actual_profit = optional_value(row, "actual_profit_yen")
        edit_href = (
            f"?edit_listing_id={listing_id}"
            f"&edit_section={section_key}"
            f"&edit_click={click_token}"
            "#management-editor"
        )
        delete_href = (
            f"?mobile_delete_listing_id={listing_id}"
            f"&mobile_delete_section={section_key}"
            f"&mobile_delete_click={click_token}"
            f"#summary-section-{section_key}"
        )
        detail_rows = [
            ("登録日", str(row.get("listing_date") or "-")),
            ("売却日", str(row.get("sold_date") or "-")),
            (
                "実利益",
                "-" if actual_profit is None else yen(actual_profit),
            ),
            (
                "配送会社",
                str(
                    row.get("shipping_carrier")
                    or row.get("expected_shipping_carrier")
                    or "-"
                ),
            ),
            (
                "配送サービス",
                str(row.get("expected_shipping_service") or "-"),
            ),
            (
                "予定送料",
                yen(
                    value(
                        row,
                        "planned_shipping_yen",
                        "international_shipping_yen",
                    )
                ),
            ),
        ]
        detail_html = "".join(
            (
                '<div class="mobile-detail-row">'
                f"<span>{html.escape(label)}</span>"
                f"<strong>{html.escape(detail_value)}</strong>"
                "</div>"
            )
            for label, detail_value in detail_rows
        )
        cards.append(
            '<article class="mobile-listing-card">'
            '<div class="mobile-card-header">'
            "<div>"
            f'<a class="mobile-card-title" target="_self" href="{edit_href}">'
            f"{html.escape(str(row.get('product_name') or ''))}</a>"
            f'<div class="mobile-card-platform">{html.escape(platform)}</div>'
            "</div>"
            f'<span class="mobile-status">{html.escape(status)}</span>'
            "</div>"
            '<div class="mobile-card-grid">'
            '<div class="mobile-card-field">'
            f"<span>{html.escape(price_label)}</span>"
            f"<strong>{html.escape(price_text)}</strong>"
            "</div>"
            '<div class="mobile-card-field">'
            "<span>仕入れ価格</span>"
            f"<strong>{html.escape(yen(value(row, 'purchase_price_yen', 'purchase_price')))}</strong>"
            "</div>"
            '<div class="mobile-card-field">'
            "<span>予定利益</span>"
            f'<strong class="{profit_class}">{html.escape(yen(profit_value))}</strong>'
            "</div>"
            '<div class="mobile-card-field">'
            "<span>利益率</span>"
            f'<strong class="{profit_class}">{value(row, "profit_margin"):.1f}%</strong>'
            "</div>"
            "</div>"
            '<div class="mobile-card-actions">'
            '<details class="mobile-card-details">'
            '<summary class="mobile-card-action detail">詳細</summary>'
            f'<div class="mobile-card-detail-content">{detail_html}</div>'
            "</details>"
            f'<a class="mobile-card-action edit" target="_self" href="{edit_href}">編集</a>'
            f'<a class="mobile-card-action delete" target="_self" href="{delete_href}">削除</a>'
            "</div>"
            "</article>"
        )
    return '<div class="mobile-listing-cards">' + "".join(cards) + "</div>"


def render_summary_status_table(
    rows: list[dict[str, object]],
    status: str,
    key_suffix: str,
    section_key: str,
) -> None:
    sort_column = st.session_state.get(f"sort_column_{section_key}", "")
    sort_direction = st.session_state.get(f"sort_order_{section_key}", "desc")
    sorted_rows = sort_summary_rows(rows, str(sort_column), str(sort_direction))
    if not sorted_rows:
        st.info(TEXT["empty"])
        return

    link_token = datetime.now().strftime("%Y%m%d%H%M%S%f")
    sort_link_token = datetime.now().strftime("%Y%m%d%H%M%S%f")

    def sortable_header(label: str, column: str, width: int) -> str:
        is_active = sort_column == column
        next_direction = "asc" if is_active and sort_direction == "desc" else "desc"
        indicator = ""
        if is_active:
            indicator = " \u25bc" if sort_direction == "desc" else " \u25b2"
        else:
            indicator = " \u2195"
        href = (
            f"?summary_sort_section={section_key}"
            f"&summary_sort_column={column}"
            f"&summary_sort_direction={next_direction}"
            f"&summary_sort_click={sort_link_token}"
            f"#summary-section-{section_key}"
        )
        return (
            f'<th style="width: {width}%;">'
            f'<a class="summary-sort-link" target="_self" href="{href}">'
            f"{html.escape(label)}{indicator}</a></th>"
        )

    table_rows = []
    is_sold_table = status == STATUS_SOLD
    for row in sorted_rows:
        listing_id = int(row["id"])
        product_name = html.escape(str(row["product_name"]))
        profit = html.escape(yen(row["profit_yen"]))
        actual_profit = html.escape(yen(row["actual_profit_yen"]))
        listing_date = html.escape(str(row.get("listing_date", "") or "-"))
        sold_date = html.escape(str(row.get("sold_date", "") or "-"))
        row_cells = [
            "<tr>"
            f'<td><a class="summary-link" target="_self" href="?edit_listing_id={listing_id}&edit_section={section_key}&edit_click={link_token}#management-editor">{product_name}</a></td>',
            f'<td class="number">{profit}</td>',
        ]
        if is_sold_table:
            row_cells.extend(
                [
                    f'<td class="number">{actual_profit}</td>',
                    f"<td>{sold_date}</td>",
                    f"<td>{listing_date}</td>",
                ]
            )
        else:
            row_cells.append(f"<td>{listing_date}</td>")
        row_cells.append("</tr>")
        table_rows.append("".join(row_cells))

    header_cells = [
        f'<th style="width: 52%;">{html.escape(TEXT["product_name"])}</th>',
        sortable_header("\u4e88\u5b9a\u5229\u76ca\uff08\u5186\uff09", "profit_yen", 18),
    ]
    if is_sold_table:
        header_cells.extend(
            [
                sortable_header(TEXT["actual_profit_yen"], "actual_profit_yen", 18),
                sortable_header(TEXT["sold_date"], "sold_date", 18),
                sortable_header(TEXT["listing_date"], "listing_date", 18),
            ]
        )
    else:
        header_cells.append(sortable_header(TEXT["listing_date"], "listing_date", 18))

    st.markdown(
        f"""
        <style>
        .summary-table {{
            width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
            font-size: 0.95rem;
        }}
        .summary-table th,
        .summary-table td {{
            border-bottom: 1px solid rgba(49, 51, 63, 0.18);
            padding: 0.45rem 0.55rem;
            vertical-align: middle;
            overflow-wrap: anywhere;
        }}
        .summary-table th {{
            background: rgba(49, 51, 63, 0.06);
            font-weight: 700;
            text-align: left;
        }}
        .summary-table .number {{
            text-align: right;
            white-space: nowrap;
        }}
        .summary-table .summary-link {{
            color: rgb(49, 51, 63);
            font-weight: 600;
            text-decoration: none;
        }}
        .summary-table .summary-link:hover {{
            text-decoration: underline;
        }}
        .summary-table .summary-sort-link {{
            color: rgb(49, 51, 63);
            text-decoration: none;
        }}
        .summary-table .summary-sort-link:hover {{
            text-decoration: underline;
        }}
        </style>
        <table class="summary-table">
            <thead>
                <tr>
                    {''.join(header_cells)}
                </tr>
            </thead>
            <tbody>
                {''.join(table_rows)}
            </tbody>
        </table>
        {build_mobile_listing_cards(sorted_rows, link_token)}
        """,
        unsafe_allow_html=True,
    )


def render_clickable_summary_table(rows: list[dict[str, object]], key_suffix: str) -> None:
    st.caption(TEXT["click_product_to_edit"])
    sections = (
        (STATUS_ACTIVE, STATUS_ACTIVE, "active", True),
        ("\u58f2\u5374\u6e08\u307f", STATUS_SOLD, "sold", False),
        (STATUS_CANCELLED, STATUS_CANCELLED, "cancelled", False),
    )
    normalized_rows = [normalize_row(row) for row in rows]
    for label, status, section_key, default_expanded in sections:
        st.session_state.setdefault(f"summary_expanded_{section_key}", default_expanded)
        status_rows = [row for row in normalized_rows if str(row.get("status", "")) == status]
        expanded = st.session_state.get(
            f"summary_expanded_{section_key}",
            default_expanded,
        )
        st.markdown(
            f'<div id="summary-section-{section_key}"></div>',
            unsafe_allow_html=True,
        )
        with st.expander(f"{label}\uff08{len(status_rows)}\u4ef6\uff09", expanded=expanded):
            render_summary_status_table(status_rows, status, key_suffix, section_key)


def filter_rows(
    rows: list[dict[str, object]],
    search_text: str,
) -> list[dict[str, object]]:
    query = search_text.strip().lower()

    filtered = []
    for row in rows:
        product_name = str(row.get("product_name", "")).lower()
        if query and query not in product_name:
            continue
        filtered.append(row)
    return filtered


def inject_responsive_css() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 1420px;
            padding-top: 0.75rem;
            padding-bottom: 4rem;
        }
        .mobile-listing-cards {
            display: none;
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
                padding: 0.55rem 0.7rem 4rem;
            }
            h1 {
                font-size: 1.3rem !important;
                line-height: 1.25 !important;
            }
            h2, h3 {
                font-size: 1.05rem !important;
                line-height: 1.3 !important;
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
            div[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) {
                flex-direction: row !important;
                flex-wrap: wrap !important;
            }
            div[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"])
            > div[data-testid="stColumn"] {
                flex: 1 1 calc(50% - 0.4rem) !important;
                width: calc(50% - 0.4rem) !important;
                min-width: 9rem !important;
            }
            div[data-testid="stNumberInput"],
            div[data-testid="stTextInput"],
            div[data-testid="stTextArea"],
            div[data-testid="stSelectbox"],
            div[data-testid="stDateInput"],
            div[data-testid="stDataFrame"] {
                width: 100% !important;
                max-width: 100% !important;
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
            div[data-testid="stTabs"] div[data-baseweb="tab-list"] {
                overflow-x: auto;
                overflow-y: hidden;
                flex-wrap: nowrap;
                scrollbar-width: thin;
            }
            div[data-testid="stTabs"] button[role="tab"] {
                min-width: max-content;
                min-height: 2.75rem;
                white-space: nowrap;
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
            .summary-table {
                display: none !important;
            }
            .mobile-listing-cards {
                display: grid;
                grid-template-columns: 1fr;
                gap: 0.75rem;
                width: 100%;
            }
            .mobile-listing-card {
                width: 100%;
                max-width: 100%;
                border: 1px solid #d8dee4;
                border: 1px solid color-mix(
                    in srgb,
                    var(--text-color, #111827) 24%,
                    transparent
                );
                border-radius: 8px;
                background: var(--secondary-background-color, #ffffff);
                color: var(--text-color, #111827);
                padding: 0.8rem;
                box-sizing: border-box;
                overflow: hidden;
            }
            .mobile-card-header {
                display: flex;
                align-items: flex-start;
                justify-content: space-between;
                gap: 0.55rem;
                margin-bottom: 0.65rem;
            }
            .mobile-card-title {
                color: var(--text-color, #111827) !important;
                font-size: 1rem;
                font-weight: 750;
                line-height: 1.35;
                text-decoration: none;
                overflow-wrap: anywhere;
            }
            .mobile-card-platform {
                color: var(--text-color, #475569);
                font-size: 0.78rem;
                margin-top: 0.18rem;
                opacity: 0.72;
            }
            .mobile-status {
                flex: 0 0 auto;
                border-radius: 999px;
                background: var(--background-color, #f1f5f9);
                color: var(--text-color, #334155);
                padding: 0.22rem 0.5rem;
                font-size: 0.72rem;
                font-weight: 700;
                white-space: nowrap;
            }
            .mobile-card-grid {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 0.5rem;
            }
            .mobile-card-field {
                min-width: 0;
                border-radius: 7px;
                background: var(--background-color, #f8fafc);
                padding: 0.5rem 0.55rem;
            }
            .mobile-card-field span {
                display: block;
                color: var(--text-color, #64748b);
                font-size: 0.7rem;
                margin-bottom: 0.12rem;
                opacity: 0.72;
            }
            .mobile-card-field strong {
                display: block;
                color: var(--text-color, #111827);
                font-size: 0.92rem;
                line-height: 1.3;
                overflow-wrap: anywhere;
            }
            .mobile-card-field strong.positive {
                color: #15803d;
            }
            .mobile-card-field strong.negative {
                color: #b91c1c;
            }
            .mobile-card-details {
                width: 100%;
                margin: 0;
            }
            .mobile-card-details summary {
                cursor: pointer;
                list-style: none;
            }
            .mobile-card-details summary::-webkit-details-marker {
                display: none;
            }
            .mobile-card-detail-content {
                margin-top: 0.55rem;
                border: 1px solid #d8dee4;
                border: 1px solid color-mix(
                    in srgb,
                    var(--text-color, #111827) 18%,
                    transparent
                );
                border-radius: 8px;
                background: var(--background-color, #f8fafc);
                padding: 0.55rem 0.65rem;
            }
            .mobile-detail-row {
                display: flex;
                justify-content: space-between;
                gap: 0.75rem;
                padding: 0.35rem 0;
                border-bottom: 1px solid #e5e7eb;
                border-bottom: 1px solid color-mix(
                    in srgb,
                    var(--text-color, #111827) 14%,
                    transparent
                );
                font-size: 0.8rem;
            }
            .mobile-detail-row span {
                color: var(--text-color, #64748b);
                opacity: 0.72;
            }
            .mobile-detail-row strong {
                color: var(--text-color, #111827);
                text-align: right;
                overflow-wrap: anywhere;
            }
            .mobile-card-actions {
                display: grid;
                grid-template-columns: 1fr;
                gap: 0.55rem;
                margin-top: 0.75rem;
            }
            .mobile-card-action {
                min-height: 2.75rem;
                border-radius: 8px;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 0.55rem;
                box-sizing: border-box;
                font-size: 0.88rem;
                font-weight: 750;
                text-decoration: none !important;
                touch-action: manipulation;
            }
            .mobile-card-action.detail {
                border: 1px solid #cbd5e1;
                border: 1px solid color-mix(
                    in srgb,
                    var(--text-color, #111827) 28%,
                    transparent
                );
                background: var(--background-color, #f8fafc);
                color: var(--text-color, #111827) !important;
            }
            .mobile-card-action.edit {
                background: #2563eb;
                color: #ffffff !important;
            }
            .mobile-card-action.delete {
                border: 1px solid #dc2626;
                background: #fff1f2;
                background: color-mix(
                    in srgb,
                    #dc2626 12%,
                    var(--background-color, #ffffff)
                );
                color: #b91c1c !important;
                color: color-mix(
                    in srgb,
                    #dc2626 82%,
                    var(--text-color, #111827)
                ) !important;
            }
            .st-key-desktop_full_list {
                display: none !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header() -> None:
    st.set_page_config(
        page_title=TEXT["app_title"],
        page_icon="\U0001f4e6",
        layout="wide",
    )
    inject_responsive_css()
    require_app_password()
    st.title(TEXT["app_title"])
    st.caption(TEXT["caption"])


def render_dashboard() -> None:
    st.subheader(TEXT["dashboard"])
    dashboard = fetch_dashboard()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(TEXT["active_count"], f"{dashboard['active_count']:,}")
    col2.metric(TEXT["sold_count"], f"{dashboard['sold_count']:,}")
    col3.metric(TEXT["cancelled_count"], f"{dashboard['cancelled_count']:,}")
    col4.metric(TEXT["registered_count"], f"{dashboard['registered_count']:,}")


def render_period_controls(key_prefix: str) -> tuple[date, date, str]:
    st.write("分析期間")
    mode_col, year_col, month_col, start_col, end_col = st.columns([1.2, 0.8, 0.8, 1, 1])
    mode = mode_col.selectbox(
        "期間",
        ("今月", "先月", "過去3か月", "今年", "年月指定", "期間指定", "全期間"),
        key=f"{key_prefix}_period_mode",
    )
    today = date.today()
    year = year_col.number_input(
        "年",
        min_value=2000,
        max_value=2100,
        value=today.year,
        step=1,
        key=f"{key_prefix}_year",
    )
    month = month_col.number_input(
        "月",
        min_value=1,
        max_value=12,
        value=today.month,
        step=1,
        key=f"{key_prefix}_month",
    )
    start = start_col.date_input(
        "開始日",
        value=date(today.year, today.month, 1),
        key=f"{key_prefix}_start",
    )
    end = end_col.date_input("終了日", value=today, key=f"{key_prefix}_end")
    start_date, end_date = period_bounds(mode, int(year), int(month), start, end)
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    return start_date, end_date, mode


def render_metric_delta(label: str, current: float, previous: float) -> None:
    if previous == 0:
        st.metric(label, yen(current), "比較データなし")
        return
    diff = current - previous
    ratio = diff / abs(previous) * 100
    st.metric(label, yen(current), f"{signed_yen(diff)}（{ratio:+.1f}%）")


def render_monthly_analytics(rows: list[dict[str, object]], start: date, end: date) -> list[dict[str, object]]:
    filtered, missing_sold_date = filter_by_period(rows, start, end)
    current = aggregate_rows(filtered)
    previous_start = add_months(date(start.year, start.month, 1), -1)
    previous_end = date(start.year, start.month, 1) - timedelta(days=1)
    previous_rows, _ = filter_by_period(rows, previous_start, previous_end)
    previous = aggregate_rows(previous_rows)

    metric_cols = st.columns(4)
    metric_cols[0].metric("売上", yen(current["売上合計"]))
    metric_cols[1].metric("実利益", yen(current["実利益合計"]))
    metric_cols[2].metric("実利益率", percent_text(current["実利益率"]))
    metric_cols[3].metric("売却件数", f"{current['売却件数']:,} 件")

    with st.expander("前月比較", expanded=True):
        delta_cols = st.columns(4)
        with delta_cols[0]:
            render_metric_delta("売上差", float(current["売上合計"] or 0), float(previous["売上合計"] or 0))
        with delta_cols[1]:
            render_metric_delta("利益差", float(current["実利益合計"] or 0), float(previous["実利益合計"] or 0))
        profit_rate_diff = None
        if current["実利益率"] is not None and previous["実利益率"] is not None:
            profit_rate_diff = float(current["実利益率"]) - float(previous["実利益率"])
        delta_cols[2].metric(
            "利益率差",
            percent_text(current["実利益率"]),
            "比較データなし" if profit_rate_diff is None else f"{profit_rate_diff:+.1f}pt",
        )
        delta_cols[3].metric(
            "件数差",
            f"{current['売却件数']:,} 件",
            f"{int(current['売却件数']) - int(previous['売却件数']):+d} 件"
            if previous["売却件数"]
            else "比較データなし",
        )

    st.caption(f"売却日未入力で月別集計から除外: {missing_sold_date} 件")
    st.metric("赤字商品", f"{current['赤字件数']:,} 件", yen(current["赤字合計"]))

    month_groups: dict[str, list[dict[str, object]]] = {}
    for row in filtered:
        key = month_key(row.get("sold_date"))
        if key:
            month_groups.setdefault(key, []).append(row)
    month_rows = []
    for key in sorted(month_groups.keys(), reverse=True):
        summary = aggregate_rows(month_groups[key])
        month_rows.append({"年月": key, **summary})
    with st.expander("月別一覧・グラフ", expanded=True):
        display_month_rows = [
            {
                "年月": row["年月"],
                "売上": round(float(row["売上合計"] or 0)),
                "実利益": round(float(row["実利益合計"] or 0)),
                "実利益率": percent_text(row["実利益率"]),
                "売却件数": row["売却件数"],
                "赤字件数": row["赤字件数"],
            }
            for row in month_rows
        ]
        st.dataframe(display_month_rows, hide_index=True, use_container_width=True)
        chart_metric = st.selectbox("グラフ表示項目", ("売上", "実利益", "実利益率(%)", "売却件数"), key="monthly_chart_metric")
        chart_rows = [
            {
                "年月": row["年月"],
                "売上": float(row["売上合計"] or 0),
                "実利益": float(row["実利益合計"] or 0),
                "実利益率(%)": row["実利益率"],
                "売却件数": row["売却件数"],
            }
            for row in month_rows
        ]
        if chart_rows:
            st.bar_chart(list(reversed(chart_rows)), x="年月", y=chart_metric)
        st.download_button(
            "月別集計CSVをダウンロード",
            data=csv_bytes(month_rows),
            file_name="monthly_analytics.csv",
            mime="text/csv",
            disabled=not month_rows,
        )

    with st.expander("選択期間の費用内訳"):
        detail = [
            {"項目": key, "金額": value}
            for key, value in current.items()
            if key not in ("実利益率",)
        ]
        st.dataframe(detail, hide_index=True, use_container_width=True)

    loss_rows = [
        {
            "商品名": row.get("product_name", ""),
            "売却日": row.get("sold_date", ""),
            "実利益": optional_value(row, "actual_profit_yen") or 0,
            "配送会社": shipping_carrier_name(row),
        }
        for row in filtered
        if (optional_value(row, "actual_profit_yen") or 0) < 0
    ]
    with st.expander("赤字商品の一覧"):
        st.dataframe(loss_rows, hide_index=True, use_container_width=True)
    return month_rows


def render_profit_variance_analysis(
    row: dict[str, object],
    key_prefix: str = "profit_variance",
) -> None:
    planned_profit = value(row, "profit_yen", "expected_profit_yen")
    actual_profit = optional_value(row, "actual_profit_yen")
    if actual_profit is None:
        actual_profit = optional_value(row, "actual_profit")
    if actual_profit is None:
        st.info("実利益が未入力のため、差額分析は表示できません。")
        return

    diff = actual_profit - planned_profit
    st.subheader("予定と実績の差額分析")
    col1, col2, col3 = st.columns(3)
    col1.metric("予定利益", yen(planned_profit))
    col2.metric("実利益", yen(actual_profit))
    col3.metric("利益差額", signed_yen(diff))

    rows = profit_variance_rows(row)
    main_causes = [
        item
        for item in rows
        if abs(float(item.get("利益への影響") or 0)) > 0
    ][:3]
    st.write("主な差額原因")
    if not main_causes:
        st.caption("大きな差額原因はありません。")
    for item in main_causes:
        impact = float(item["利益への影響"] or 0)
        color = "#0f8a3b" if impact > 0 else "#b42318" if impact < 0 else "#6b7280"
        st.markdown(
            f"<div style='color:{color}; font-weight:600;'>{html.escape(str(item['項目']))}: "
            f"{html.escape(str(item['状態']))} {html.escape(signed_yen(impact))}</div>"
            f"<div style='color:#6b7280; margin-bottom:0.4rem;'>{html.escape(str(item['説明']))}</div>",
            unsafe_allow_html=True,
        )

    with st.expander("すべての差額を見る"):
        display_rows = []
        for item in rows:
            planned = item["予定値"]
            actual = item["実績値"]
            diff_value = item["差額"]
            display_rows.append(
                {
                    "項目": item["項目"],
                    "予定値": yen(planned) if isinstance(planned, (int, float)) else planned,
                    "実績値": yen(actual) if isinstance(actual, (int, float)) else actual,
                    "差額": signed_yen(diff_value) if isinstance(diff_value, (int, float)) else diff_value,
                    "利益への影響": signed_yen(float(item["利益への影響"] or 0)),
                    "状態": item["状態"],
                    "説明": item["説明"],
                }
            )
        st.dataframe(display_rows, hide_index=True, use_container_width=True)
        st.download_button(
            "商品別差額原因CSVをダウンロード",
            data=csv_bytes(display_rows),
            file_name=f"profit_variance_{row.get('id', '')}.csv",
            mime="text/csv",
            disabled=not display_rows,
            key=f"{key_prefix}_download_{row.get('id', '')}",
        )


def render_shipping_analytics(rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    carrier_rows = aggregate_by_key(rows, shipping_carrier_name)
    service_rows = aggregate_by_key(rows, lambda row: f"{shipping_carrier_name(row)} / {shipping_service_name(row)}")

    if carrier_rows:
        cheapest = min(
            [row for row in carrier_rows if row["平均実送料"] is not None],
            key=lambda row: float(row["平均実送料"]),
            default=None,
        )
        best_profit = max(carrier_rows, key=lambda row: float(row["平均実利益"] or 0), default=None)
        best_margin = max(
            [row for row in carrier_rows if row["実利益率"] is not None],
            key=lambda row: float(row["実利益率"]),
            default=None,
        )
        smallest_diff = min(
            [row for row in carrier_rows if row["平均送料差額"] is not None],
            key=lambda row: abs(float(row["平均送料差額"])),
            default=None,
        )
        lowest_loss_rate = min(
            carrier_rows,
            key=lambda row: (float(row["赤字件数"]) / float(row["発送件数"])) if row["発送件数"] else 1,
            default=None,
        )
        recommendation_rows = [
            {"分析": "平均送料が最も安い配送会社", "結果": cheapest["区分"] if cheapest else "データなし"},
            {"分析": "平均利益が最も高い配送会社", "結果": best_profit["区分"] if best_profit else "データなし"},
            {"分析": "利益率が最も高い配送会社", "結果": best_margin["区分"] if best_margin else "データなし"},
            {"分析": "予定送料との差が最も小さい配送会社", "結果": smallest_diff["区分"] if smallest_diff else "データなし"},
            {"分析": "赤字率が最も低い配送会社", "結果": lowest_loss_rate["区分"] if lowest_loss_rate else "データなし"},
        ]
        st.dataframe(recommendation_rows, hide_index=True, use_container_width=True)

    st.write("配送会社別集計")
    display_carriers = []
    for row in carrier_rows:
        display = dict(row)
        display["実利益率"] = percent_text(display["実利益率"])
        display_carriers.append(display)
    st.dataframe(display_carriers, hide_index=True, use_container_width=True)

    with st.expander("配送サービス別集計"):
        display_services = []
        for row in service_rows:
            display = dict(row)
            display["実利益率"] = percent_text(display["実利益率"])
            display_services.append(display)
        st.dataframe(display_services, hide_index=True, use_container_width=True)

    with st.expander("重量帯別分析"):
        weight_rows = aggregate_by_key(
            rows,
            lambda row: f"{shipping_carrier_name(row)} / {weight_band(optional_value(row, 'shipping_weight_g') or optional_value(row, 'package_weight_g'))}",
        )
        for row in weight_rows:
            row["実利益率"] = percent_text(row["実利益率"])
        st.dataframe(weight_rows, hide_index=True, use_container_width=True)

    with st.expander("配送会社×配送先国"):
        country_rows = aggregate_by_key(
            rows,
            lambda row: f"{shipping_carrier_name(row)} / {row.get('destination_country') or '配送先未入力'}",
        )
        compact_rows = [
            {
                "区分": row["区分"],
                "件数": row["発送件数"],
                "平均送料": row["平均実送料"],
                "平均利益": row["平均実利益"],
                "利益率": percent_text(row["実利益率"]),
            }
            for row in country_rows
        ]
        st.dataframe(compact_rows, hide_index=True, use_container_width=True)

    csv_col1, csv_col2 = st.columns(2)
    csv_col1.download_button(
        "配送会社別集計CSVをダウンロード",
        data=csv_bytes(display_carriers),
        file_name="shipping_carrier_analytics.csv",
        mime="text/csv",
        disabled=not display_carriers,
    )
    csv_col2.download_button(
        "配送サービス別集計CSVをダウンロード",
        data=csv_bytes(display_services if 'display_services' in locals() else []),
        file_name="shipping_service_analytics.csv",
        mime="text/csv",
        disabled=not service_rows,
    )
    return carrier_rows, service_rows


def render_analytics(rows: list[dict[str, object]]) -> None:
    st.subheader("分析・集計")
    all_sold = sold_rows(rows)
    if not all_sold:
        st.info("売却済みで実利益が保存されたデータがまだありません。")
        return

    start_date, end_date, _ = render_period_controls("aggregate")
    filtered, _ = filter_by_period(all_sold, start_date, end_date)
    excluded = len(all_sold) - len(filtered)

    summary = aggregate_rows(filtered)
    carrier_rows = aggregate_by_key(filtered, shipping_carrier_name) if filtered else []
    best_margin = max(
        [row for row in carrier_rows if row["実利益率"] is not None],
        key=lambda row: float(row["実利益率"]),
        default=None,
    )
    st.write("サマリー")
    previous_month_start = add_months(date(start_date.year, start_date.month, 1), -1)
    previous_month_end = date(start_date.year, start_date.month, 1) - timedelta(days=1)
    previous_rows, _ = filter_by_period(all_sold, previous_month_start, previous_month_end)
    previous_summary = aggregate_rows(previous_rows)
    cols = st.columns(6)
    cols[0].metric("売上", yen(summary["売上合計"]))
    cols[1].metric("実利益", yen(summary["実利益合計"]))
    cols[2].metric("実利益率", percent_text(summary["実利益率"]))
    cols[3].metric("売却件数", f"{summary['売却件数']:,} 件")
    cols[4].metric("赤字件数", f"{summary['赤字件数']:,} 件")
    previous_profit = float(previous_summary["実利益合計"] or 0)
    current_profit = float(summary["実利益合計"] or 0)
    if previous_profit:
        profit_delta = current_profit - previous_profit
        cols[5].metric(
            "前月比（利益）",
            signed_yen(profit_delta),
            f"{profit_delta / abs(previous_profit) * 100:+.1f}%",
        )
    else:
        cols[5].metric("前月比（利益）", "比較データなし")
    st.caption(
        f"対象期間: {start_date.isoformat()} ～ {end_date.isoformat()} / 期間外または売却日未入力: {excluded} 件 / "
        f"最も利益率が高い配送会社: {best_margin['区分'] if best_margin else 'データなし'}"
    )

    tab_month, tab_shipping = st.tabs(("月別集計", "配送会社別分析"))
    with tab_month:
        render_monthly_analytics(all_sold, start_date, end_date)
    with tab_shipping:
        render_shipping_analytics(filtered)


def render_variance_analytics(rows: list[dict[str, object]]) -> None:
    st.subheader("予定と実績の差額分析")
    all_sold = sold_rows(rows)
    if not all_sold:
        st.info("売却済みで実利益が保存されたデータがまだありません。")
        return

    start_date, end_date, _ = render_period_controls("variance")
    variance_targets, missing_sold_date = filter_by_period(all_sold, start_date, end_date)
    if not variance_targets:
        st.info("選択期間に差額分析できる売却済みデータがありません。")
        st.caption(f"売却日未入力: {missing_sold_date} 件")
        return

    options = {
        int(row["id"]): f"#{row['id']} {row.get('product_name', '')} / {row.get('sold_date', '')}"
        for row in variance_targets
    }
    selected_id = st.selectbox(
        "差額原因を見る商品",
        options=list(options.keys()),
        format_func=lambda listing_id: options[int(listing_id)],
        key="variance_listing_id",
    )
    selected = next(row for row in variance_targets if int(row["id"]) == int(selected_id))
    render_profit_variance_analysis(
        selected,
        key_prefix=f"variance_tab_{selected.get('id', '')}",
    )

    variance_csv = []
    for row in variance_targets:
        for item in profit_variance_rows(row):
            variance_csv.append(
                {
                    "ID": row.get("id"),
                    "商品名": row.get("product_name"),
                    "売却日": row.get("sold_date"),
                    **item,
                }
            )
    st.download_button(
        "商品別差額原因CSVをまとめてダウンロード",
        data=csv_bytes(variance_csv),
        file_name="profit_variance_all.csv",
        mime="text/csv",
        disabled=not variance_csv,
        key="variance_tab_all_csv",
    )


def render_listing_edit_form(selected: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    selected_id = int(selected["id"])
    expanded = (
        st.session_state.get("duplicated_listing_id") == selected_id
        or st.session_state.get("focus_listing_id") == selected_id
    )
    updates: dict[str, object] = {}
    draft_selected = dict(selected)
    with st.expander(TEXT["edit_listing"], expanded=expanded):
        listing_date_value = selected.get("listing_date") or date.today().isoformat()
        if str(selected["platform"]) in PLATFORM_OPTIONS:
            platform_index = PLATFORM_OPTIONS.index(str(selected["platform"]))
        else:
            platform_index = 0

        col1, col2, col3 = st.columns(3)
        product_name = col1.text_input(
            TEXT["product_name"],
            value=str(selected.get("product_name", "")),
            key=f"edit_product_name_{selected['id']}",
        )
        platform = col2.selectbox(
            TEXT["platform"],
            PLATFORM_OPTIONS,
            index=platform_index,
            key=f"edit_platform_{selected['id']}",
        )
        listing_date_value = col3.date_input(
            TEXT["listing_date"],
            value=date.fromisoformat(str(listing_date_value)),
            key=f"edit_listing_date_{selected['id']}",
        )

        common_updates = {
            "product_name": product_name.strip() or str(selected["product_name"]),
            "platform": platform,
            "listing_date": listing_date_value.isoformat(),
        }
        if is_simple_platform(platform):
            price_col1, price_col2 = st.columns(2)
            listing_price_usd = price_col1.number_input(
                "売却価格（円）"
                if platform == PLATFORM_IPHONE_RESALE
                else "販売価格（円）",
                min_value=0.0,
                value=float(selected["sale_price_usd"]),
                step=100.0,
                format="%.0f",
                key=f"edit_simple_listing_price_yen_{selected['id']}",
            )
            purchase_price_yen = price_col2.number_input(
                TEXT["purchase_price_yen"],
                min_value=0.0,
                value=float(selected["purchase_price_yen"]),
                step=100.0,
                format="%.0f",
                key=f"edit_simple_purchase_price_yen_{selected['id']}",
            )

            iphone_model = ""
            iphone_capacity = ""
            if platform == PLATFORM_IPHONE_RESALE:
                model_col, capacity_col = st.columns(2)
                iphone_model = model_col.text_input(
                    TEXT["iphone_model"],
                    value=str(selected.get("iphone_model") or ""),
                    key=f"edit_iphone_model_{selected['id']}",
                )
                iphone_capacity = capacity_col.text_input(
                    TEXT["iphone_capacity"],
                    value=str(selected.get("iphone_capacity") or ""),
                    key=f"edit_iphone_capacity_{selected['id']}",
                )

            sales_fee_input_mode = FEE_MODE_AMOUNT
            sales_fee_rate = 0.0
            sales_fee_yen = 0.0
            other_cost_yen = 0.0
            repair_cost_yen = 0.0
            parts_cost_yen = 0.0
            if platform == PLATFORM_IPHONE_RESALE:
                simple_shipping_yen = st.number_input(
                    TEXT["simple_shipping_yen"],
                    min_value=0.0,
                    value=float(
                        selected.get("simple_shipping_yen")
                        or selected.get("international_shipping_yen")
                        or 0
                    ),
                    step=100.0,
                    format="%.0f",
                    key=f"edit_simple_shipping_yen_{selected['id']}",
                )
            else:
                stored_fee_mode = str(
                    selected.get("sales_fee_input_mode") or FEE_MODE_RATE
                )
                fee_mode_label = st.radio(
                    TEXT["sales_fee_input_mode"],
                    ("料率（%）", "金額（円）"),
                    index=0 if stored_fee_mode == FEE_MODE_RATE else 1,
                    horizontal=True,
                    key=f"edit_sales_fee_mode_{selected['id']}",
                )
                sales_fee_input_mode = (
                    FEE_MODE_RATE
                    if fee_mode_label == "料率（%）"
                    else FEE_MODE_AMOUNT
                )
                fee_col, shipping_col, other_col = st.columns(3)
                sales_fee_rate = float(selected.get("sales_fee_rate") or 0)
                sales_fee_yen = float(selected.get("sales_fee_yen") or 0)
                if sales_fee_input_mode == FEE_MODE_RATE:
                    sales_fee_rate = fee_col.number_input(
                        TEXT["sales_fee_rate"],
                        min_value=0.0,
                        max_value=100.0,
                        value=sales_fee_rate,
                        step=0.1,
                        format="%.2f",
                        key=f"edit_sales_fee_rate_{selected['id']}",
                    )
                else:
                    sales_fee_yen = fee_col.number_input(
                        TEXT["sales_fee_yen"],
                        min_value=0.0,
                        value=sales_fee_yen,
                        step=100.0,
                        format="%.0f",
                        key=f"edit_sales_fee_yen_{selected['id']}",
                    )
                simple_shipping_yen = shipping_col.number_input(
                    TEXT["simple_shipping_yen"],
                    min_value=0.0,
                    value=float(
                        selected.get("simple_shipping_yen")
                        or selected.get("international_shipping_yen")
                        or 0
                    ),
                    step=100.0,
                    format="%.0f",
                    key=f"edit_simple_shipping_yen_{selected['id']}",
                )
                other_cost_yen = other_col.number_input(
                    "その他経費（円）",
                    min_value=0.0,
                    value=float(selected.get("other_cost_yen") or 0),
                    step=100.0,
                    format="%.0f",
                    key=f"edit_simple_other_cost_yen_{selected['id']}",
                )
            platform_memo = st.text_area(
                TEXT["platform_memo"],
                value=str(selected.get("platform_memo") or ""),
                height=90,
                key=f"edit_platform_memo_{selected['id']}",
            )
            updates = {
                **common_updates,
                "currency_code": "JPY",
                "usd_jpy_rate": 0.0,
                "listing_price_usd": listing_price_usd,
                "buyer_shipping_usd": 0.0,
                "exchange_rate": 1.0,
                "purchase_price_yen": purchase_price_yen,
                "domestic_shipping_yen": 0.0,
                "international_shipping_yen": simple_shipping_yen,
                "packaging_yen": 0.0,
                "other_cost_yen": other_cost_yen,
                "ebay_fee_rate": sales_fee_rate,
                "promoted_listing_rate": 0.0,
                "exchange_spread_rate": 0.0,
                "fixed_fee_usd": 0.0,
                "target_profit_yen": 0.0,
                "sales_fee_input_mode": sales_fee_input_mode,
                "sales_fee_rate": sales_fee_rate,
                "sales_fee_yen": sales_fee_yen,
                "simple_shipping_yen": simple_shipping_yen,
                "repair_cost_yen": repair_cost_yen,
                "parts_cost_yen": parts_cost_yen,
                "iphone_model": iphone_model,
                "iphone_capacity": iphone_capacity,
                "platform_memo": platform_memo,
            }
        else:
            stored_currency = listing_currency(selected)
            currency_code = st.selectbox(
                "販売通貨",
                SUPPORTED_CURRENCIES,
                index=SUPPORTED_CURRENCIES.index(stored_currency),
                format_func=currency_option_label,
                key=f"edit_currency_code_{selected['id']}",
            )
            price_col1, price_col2, price_col3, price_col4 = st.columns(4)
            listing_price_usd = price_col1.number_input(
                foreign_amount_label("販売価格", currency_code),
                min_value=0.0,
                value=float(selected["sale_price_usd"]),
                step=1.0,
                format="%.2f",
                key=f"edit_listing_price_usd_{selected['id']}",
            )
            buyer_shipping_usd = price_col2.number_input(
                foreign_amount_label(
                    "購入者から受け取る送料",
                    currency_code,
                ),
                min_value=0.0,
                value=float(selected.get("buyer_shipping_usd") or 0),
                step=1.0,
                format="%.2f",
                key=f"edit_buyer_shipping_usd_{selected['id']}",
            )
            exchange_rate = price_col3.number_input(
                f"予定為替レート（{currency_code}/JPY）",
                min_value=0.01,
                value=float(
                    selected.get("exchange_rate")
                    or read_shared_exchange_rate(currency_code)
                    or DEFAULT_JPY_RATES[currency_code]
                ),
                step=0.0001,
                format="%.4f",
                key=f"edit_exchange_rate_{selected['id']}",
            )
            usd_jpy_rate = price_col4.number_input(
                "固定手数料換算用USD/JPY",
                min_value=0.01,
                value=float(planned_usd_jpy_rate(selected)),
                step=0.0001,
                format="%.4f",
                key=f"edit_usd_jpy_rate_{selected['id']}",
            )

            cost_col1, cost_col2, cost_col3 = st.columns(3)
            purchase_price_yen = cost_col1.number_input(
                TEXT["purchase_price_yen"],
                min_value=0.0,
                value=float(selected["purchase_price_yen"]),
                step=100.0,
                format="%.0f",
                key=f"edit_purchase_price_yen_{selected['id']}",
            )
            domestic_shipping_yen = cost_col2.number_input(
                TEXT["domestic_shipping_yen"],
                min_value=0.0,
                value=float(selected.get("domestic_shipping_yen") or 0),
                step=100.0,
                format="%.0f",
                key=f"edit_domestic_shipping_yen_{selected['id']}",
            )
            international_shipping_yen = cost_col3.number_input(
                TEXT["international_shipping_yen"],
                min_value=0.0,
                value=float(selected["international_shipping_yen"]),
                step=100.0,
                format="%.0f",
                key=f"edit_international_shipping_yen_{selected['id']}",
            )
            render_shipping_breakdown(selected)

            misc_col1, misc_col2, misc_col3 = st.columns(3)
            packaging_yen = misc_col1.number_input(
                TEXT["packaging_yen"],
                min_value=0.0,
                value=float(selected.get("packaging_yen") or 0),
                step=50.0,
                format="%.0f",
                key=f"edit_packaging_yen_{selected['id']}",
            )
            other_cost_yen = misc_col2.number_input(
                TEXT["other_cost_yen"],
                min_value=0.0,
                value=float(selected["other_cost_yen"]),
                step=100.0,
                format="%.0f",
                key=f"edit_other_cost_yen_{selected['id']}",
            )
            target_profit_yen = misc_col3.number_input(
                TEXT["target_profit_yen"],
                min_value=0.0,
                value=float(selected["target_profit_yen"]),
                step=100.0,
                format="%.0f",
                key=f"edit_target_profit_yen_{selected['id']}",
            )

            fee_col1, fee_col2, fee_col3, fee_col4 = st.columns(4)
            ebay_fee_rate = fee_col1.number_input(
                TEXT["ebay_fee_rate"],
                min_value=0.0,
                max_value=99.0,
                value=float(selected.get("ebay_fee_rate") or 0),
                step=0.1,
                format="%.2f",
                key=f"edit_ebay_fee_rate_{selected['id']}",
            )
            promoted_listing_rate = fee_col2.number_input(
                TEXT["promoted_listing_rate"],
                min_value=0.0,
                max_value=99.0,
                value=float(selected.get("promoted_listing_rate") or 0),
                step=0.5,
                format="%.2f",
                key=f"edit_promoted_listing_rate_{selected['id']}",
            )
            exchange_spread_rate = fee_col3.number_input(
                TEXT["exchange_spread_rate"],
                min_value=0.0,
                max_value=99.0,
                value=float(selected.get("exchange_spread_rate") or 0),
                step=0.1,
                format="%.2f",
                key=f"edit_exchange_spread_rate_{selected['id']}",
            )
            fixed_fee_usd = fee_col4.number_input(
                TEXT["fixed_fee_usd"],
                min_value=0.0,
                value=float(selected.get("fixed_fee_usd") or 0),
                step=0.05,
                format="%.2f",
                key=f"edit_fixed_fee_usd_{selected['id']}",
            )
            updates = {
                **common_updates,
                "currency_code": currency_code,
                "usd_jpy_rate": usd_jpy_rate,
                "listing_price_usd": listing_price_usd,
                "buyer_shipping_usd": buyer_shipping_usd,
                "exchange_rate": exchange_rate,
                "purchase_price_yen": purchase_price_yen,
                "domestic_shipping_yen": domestic_shipping_yen,
                "international_shipping_yen": international_shipping_yen,
                "packaging_yen": packaging_yen,
                "other_cost_yen": other_cost_yen,
                "ebay_fee_rate": ebay_fee_rate,
                "promoted_listing_rate": promoted_listing_rate,
                "exchange_spread_rate": exchange_spread_rate,
                "fixed_fee_usd": fixed_fee_usd,
                "target_profit_yen": target_profit_yen,
                "sales_fee_input_mode": FEE_MODE_RATE,
                "sales_fee_rate": 0.0,
                "sales_fee_yen": 0.0,
                "simple_shipping_yen": 0.0,
                "repair_cost_yen": 0.0,
                "parts_cost_yen": 0.0,
                "iphone_model": "",
                "iphone_capacity": "",
                "platform_memo": str(selected.get("platform_memo") or ""),
            }
        expected = calculate_expected_values(updates)
        draft_selected.update(updates)
        draft_selected.update(
            {
                "listing_price": updates["listing_price_usd"],
                "sale_price_usd": updates["listing_price_usd"],
                "purchase_price": updates["purchase_price_yen"],
                "expected_shipping": updates["international_shipping_yen"],
                "ebay_fee_yen": expected["ebay_fee_yen"],
                "sales_fee_yen": (
                    expected["ebay_fee_yen"]
                    if is_simple_profit_platform(updates)
                    else updates.get("sales_fee_yen", 0.0)
                ),
                "ad_fee_yen": expected["ad_fee_yen"],
                "expected_profit_yen": expected["expected_profit_yen"],
                "profit_yen": expected["profit_yen"],
                "profit_margin": expected["profit_margin"],
                "roi": expected["roi"],
                "gross_sales_yen": expected["gross_sales_yen"],
                "break_even_sale_price_usd": expected["break_even_sale_price_usd"],
                "target_sale_price_usd": expected["target_sale_price_usd"],
            }
        )
        st.metric(TEXT["profit_yen"], yen(expected["profit_yen"]))

        if st.button(TEXT["save_listing_edits"], type="primary", key=f"save_listing_edits_{selected['id']}"):
            update_listing_details(int(selected["id"]), updates)
            keep_summary_section_for_status(
                str(selected.get("status", STATUS_ACTIVE)),
                int(selected["id"]),
                scroll=True,
            )
            st.session_state.pop("duplicated_listing_id", None)
            st.success(TEXT["listing_saved"])
            st.rerun()

    return updates, normalize_row(draft_selected)


def render_management(rows: list[dict[str, object]], exchange_rate: float) -> None:
    st.subheader(TEXT["listing_management"])
    if st.button(TEXT["refresh"]):
        st.rerun()

    if not rows:
        st.info(TEXT["empty"])
        st.caption(
            f"{TEXT['database_file']}: {database_location_label(DB_PATH)}"
        )
        return

    apply_listing_query_params(rows)
    apply_summary_sort_query_params()
    apply_mobile_delete_query_params(rows)
    st.markdown('<div id="summary-list"></div>', unsafe_allow_html=True)
    search_col, platform_col = st.columns([1.4, 1])
    search_text = search_col.text_input(
        TEXT["search"],
        placeholder=TEXT["search_placeholder"],
        key="management_search",
    )
    platform_filter = platform_col.selectbox(
        TEXT["platform_filter"],
        (PLATFORM_ALL, *PLATFORM_OPTIONS),
        key="summary_platform_filter",
    )
    searched_rows = filter_rows(rows, search_text)
    summary_rows = filter_rows_by_platform(searched_rows, platform_filter)
    render_mobile_delete_confirmation(rows)
    st.write(TEXT["summary_list"])
    render_clickable_summary_table(summary_rows, platform_filter)
    if st.session_state.get("scroll_to_summary_section"):
        scroll_to_summary_section(str(st.session_state["scroll_to_summary_section"]))
        st.session_state.pop("scroll_to_summary_section", None)
    with st.expander(TEXT["full_list"]):
        with st.container(key="desktop_full_list"):
            st.dataframe(
                format_rows(summary_rows),
                hide_index=True,
                use_container_width=True,
            )
        st.markdown(
            build_mobile_listing_cards(
                [normalize_row(row) for row in summary_rows],
                datetime.now().strftime("%Y%m%d%H%M%S%f"),
            ),
            unsafe_allow_html=True,
        )
    st.caption(f"{TEXT['database_file']}: {database_location_label(DB_PATH)}")

    st.markdown('<div id="management-editor"></div>', unsafe_allow_html=True)
    st.subheader(TEXT["select_listing"])
    management_rows = summary_rows

    if not management_rows:
        st.info(TEXT["no_management_results"])
        return

    labels = {
        int(row["id"]): f"#{row['id']} - {row['product_name']} / {platform_value(row)} ({row['status']})"
        for row in management_rows
    }
    selected_id = st.selectbox(
        TEXT["select_listing"],
        options=list(labels.keys()),
        format_func=lambda listing_id: labels[int(listing_id)],
        index=(
            list(labels.keys()).index(st.session_state.selected_listing_id)
            if st.session_state.get("selected_listing_id") in labels
            else 0
        ),
    )
    st.session_state.selected_listing_id = int(selected_id)
    selected = normalize_row(next(row for row in management_rows if int(row["id"]) == int(selected_id)))
    if st.session_state.get("scroll_to_listing_id") == int(selected_id):
        scroll_to_management_editor()
        st.session_state.pop("scroll_to_listing_id", None)
    edit_updates, draft_selected = render_listing_edit_form(selected)
    st.caption(f"{TEXT['platform']}: {draft_selected['platform']}")

    status = st.selectbox(
        TEXT["status"],
        STATUS_OPTIONS,
        index=STATUS_OPTIONS.index(str(selected["status"])),
        key=f"status_{selected_id}",
    )

    actual_sale_price_usd = None
    actual_buyer_shipping_usd = None
    actual_ebay_fee_usd = None
    actual_ad_fee_usd = None
    actual_fixed_fee_usd = None
    actual_usd_jpy_rate_value = None
    actual_order_revenue_yen = None
    effective_ebay_fee_rate = None
    effective_ad_fee_rate = None
    actual_shipping_yen = None
    shipping_carrier = None
    shipping_service = None
    shipping_weight_g = None
    actual_profit_yen = None
    actual_profit_margin = None
    sold_date = None
    actual_details: dict[str, float | None] = {}
    if status == STATUS_SOLD:
        currency_code = listing_currency(draft_selected)
        actual_defaults = actual_fee_defaults(draft_selected, exchange_rate)
        actual_usd_jpy_rate_value = actual_usd_jpy_rate(draft_selected)
        actual_defaults_suffix = (
            f"{actual_defaults['actual_sale_price_usd']:.2f}_"
            f"{actual_defaults['actual_buyer_shipping_usd']:.2f}_"
            f"{actual_defaults['actual_ebay_fee_usd']:.2f}_"
            f"{actual_defaults['actual_ad_fee_usd']:.2f}_"
            f"{actual_defaults['actual_fixed_fee_usd']:.2f}_"
            f"{actual_usd_jpy_rate_value:.4f}_"
            f"{actual_defaults['actual_shipping_yen']:.0f}"
        )
        sold_date_value = selected.get("sold_date") or date.today().isoformat()
        if is_simple_profit_platform(draft_selected):
            sold_col, sale_col = st.columns(2)
            sold_date = sold_col.date_input(
                TEXT["sold_date"],
                value=date.fromisoformat(str(sold_date_value)),
                key=f"sold_date_{selected_id}",
            )
            actual_sale_price_usd = sale_col.number_input(
                "実際の売却価格（円）"
                if platform_value(draft_selected) == PLATFORM_IPHONE_RESALE
                else "実際の販売価格（円）",
                min_value=0.0,
                value=actual_defaults["actual_sale_price_usd"],
                step=100.0,
                format="%.0f",
                key=f"actual_simple_sale_price_yen_{selected_id}_{actual_defaults_suffix}",
            )
            actual_buyer_shipping_usd = 0.0
            actual_exchange_rate = 1.0
            actual_usd_jpy_rate_value = 1.0
            actual_ebay_fee_usd = 0.0
            actual_ad_fee_usd = 0.0
            actual_fixed_fee_usd = 0.0
        else:
            col1, col2, col3, col4, col5 = st.columns(5)
            sold_date = col1.date_input(
                TEXT["sold_date"],
                value=date.fromisoformat(str(sold_date_value)),
                key=f"sold_date_{selected_id}",
            )
            actual_sale_price_usd = col2.number_input(
                foreign_amount_label("実際の販売価格", currency_code),
                min_value=0.0,
                value=actual_defaults["actual_sale_price_usd"],
                step=1.0,
                format="%.2f",
                key=f"actual_sale_price_usd_{selected_id}_{actual_defaults_suffix}",
            )
            actual_buyer_shipping_usd = col3.number_input(
                foreign_amount_label(
                    "購入者から受け取った送料",
                    currency_code,
                ),
                min_value=0.0,
                value=actual_defaults["actual_buyer_shipping_usd"],
                step=1.0,
                format="%.2f",
                key=f"actual_buyer_shipping_usd_{selected_id}_{actual_defaults_suffix}",
            )
            actual_exchange_rate = col4.number_input(
                f"実績為替レート（{currency_code}/JPY）",
                min_value=0.0001,
                value=float(
                    optional_value(selected, "actual_exchange_rate")
                    or value(selected, "exchange_rate")
                    or exchange_rate
                ),
                step=0.01,
                format="%.4f",
                key=f"actual_exchange_rate_{selected_id}",
            )
            actual_usd_jpy_rate_value = col5.number_input(
                TEXT["actual_usd_jpy_rate"],
                min_value=0.0001,
                value=float(actual_usd_jpy_rate_value),
                step=0.01,
                format="%.4f",
                key=f"actual_usd_jpy_rate_{selected_id}",
            )

            fee_col1, fee_col2, fee_col3, fee_col4 = st.columns(4)
            actual_ebay_fee_usd = fee_col1.number_input(
                TEXT["actual_ebay_fee_usd"],
                min_value=0.0,
                value=actual_defaults["actual_ebay_fee_usd"],
                step=0.1,
                format="%.2f",
                key=f"actual_ebay_fee_usd_{selected_id}_{actual_defaults_suffix}",
            )
            actual_ad_fee_usd = fee_col2.number_input(
                TEXT["actual_ad_fee_usd"],
                min_value=0.0,
                value=actual_defaults["actual_ad_fee_usd"],
                step=0.1,
                format="%.2f",
                key=f"actual_ad_fee_usd_{selected_id}_{actual_defaults_suffix}",
            )
            actual_fixed_fee_usd = fee_col3.number_input(
                TEXT["actual_fixed_fee_usd"],
                min_value=0.0,
                value=actual_defaults["actual_fixed_fee_usd"],
                step=0.05,
                format="%.2f",
                key=f"actual_fixed_fee_usd_{selected_id}_{actual_defaults_suffix}",
            )
            actual_order_revenue_yen = calculate_order_revenue_yen(
                actual_exchange_rate,
                actual_sale_price_usd,
                actual_buyer_shipping_usd,
                actual_ebay_fee_usd,
                actual_ad_fee_usd,
                actual_fixed_fee_usd,
                actual_usd_jpy_rate_value,
            )
            fee_col4.metric(
                TEXT["actual_order_revenue_yen"],
                yen(actual_order_revenue_yen),
            )

        shipping_col1, shipping_col2, shipping_col3, shipping_col4 = st.columns(4)
        actual_shipping_yen = shipping_col1.number_input(
            TEXT["actual_shipping_yen"],
            min_value=0.0,
            value=actual_defaults["actual_shipping_yen"],
            step=100.0,
            format="%.0f",
            key=f"actual_shipping_yen_{selected_id}_{actual_defaults_suffix}",
        )
        current_shipping_carrier = default_actual_shipping_carrier(selected)
        shipping_carrier_options = SHIPPING_CARRIER_OPTIONS
        if current_shipping_carrier and current_shipping_carrier not in shipping_carrier_options:
            shipping_carrier_options = (current_shipping_carrier, *SHIPPING_CARRIER_OPTIONS)
        shipping_carrier = shipping_col2.selectbox(
            TEXT["shipping_carrier"],
            options=shipping_carrier_options,
            index=(
                shipping_carrier_options.index(current_shipping_carrier)
                if current_shipping_carrier in shipping_carrier_options
                else 0
            ),
            format_func=lambda carrier: "未選択" if carrier == "" else carrier,
            key=f"shipping_carrier_{selected_id}",
        )
        current_shipping_service = str(
            selected.get("shipping_service")
            or selected.get("expected_shipping_service")
            or ""
        )
        if shipping_carrier != current_shipping_carrier:
            current_shipping_service = (
                "SpeedPAK Economy"
                if shipping_carrier == "SpeedPAK Economy"
                else ""
            )
        shipping_service = shipping_col3.text_input(
            TEXT["shipping_service"],
            value=current_shipping_service,
            placeholder="例: 小形包装物 / Economy",
            key=f"shipping_service_{selected_id}_{shipping_carrier}",
        )
        default_shipping_weight_g = float(
            selected.get("shipping_weight_g")
            or selected.get("package_weight_g")
            or selected.get("research_shipping_weight_g")
            or 0
        )
        shipping_weight_input = shipping_col4.number_input(
            TEXT["shipping_weight_g"],
            min_value=0.0,
            value=default_shipping_weight_g,
            step=10.0,
            format="%.0f",
            key=f"shipping_weight_g_{selected_id}_{default_shipping_weight_g:.0f}",
        )
        shipping_weight_g = shipping_weight_input if shipping_weight_input > 0 else None
        detail_source = dict(draft_selected)
        detail_source["actual_exchange_rate"] = actual_exchange_rate
        detail_defaults = actual_detail_defaults(
            detail_source,
            actual_exchange_rate,
            actual_sale_price_usd,
            actual_buyer_shipping_usd,
            actual_shipping_yen,
        )
        actual_purchase_default_suffix = (
            f"{detail_defaults['actual_purchase_price_yen']:.0f}"
        )
        with st.expander("実績費用の内訳", expanded=False):
            st.caption("ここで入力した費用を売却実績として保存します。")
            if is_simple_profit_platform(draft_selected):
                if platform_value(draft_selected) == PLATFORM_IPHONE_RESALE:
                    actual_purchase_price_yen = st.number_input(
                        TEXT["actual_purchase_price_yen"],
                        min_value=0.0,
                        value=detail_defaults["actual_purchase_price_yen"],
                        step=100.0,
                        format="%.0f",
                        key=(
                            f"actual_purchase_price_yen_{selected_id}_"
                            f"{actual_purchase_default_suffix}"
                        ),
                    )
                    actual_sales_fee_yen = 0.0
                    actual_other_cost_yen = 0.0
                else:
                    cost_col1, cost_col2, cost_col3 = st.columns(3)
                    actual_purchase_price_yen = cost_col1.number_input(
                        TEXT["actual_purchase_price_yen"],
                        min_value=0.0,
                        value=detail_defaults["actual_purchase_price_yen"],
                        step=100.0,
                        format="%.0f",
                        key=(
                            f"actual_purchase_price_yen_{selected_id}_"
                            f"{actual_purchase_default_suffix}"
                        ),
                    )
                    actual_sales_fee_yen = cost_col2.number_input(
                        "実際の販売手数料（円）",
                        min_value=0.0,
                        value=detail_defaults["actual_sales_fee_yen"],
                        step=100.0,
                        format="%.0f",
                        key=f"actual_sales_fee_yen_{selected_id}",
                    )
                    actual_other_cost_yen = cost_col3.number_input(
                        "実際のその他経費（円）",
                        min_value=0.0,
                        value=detail_defaults["actual_other_cost_yen"],
                        step=100.0,
                        format="%.0f",
                        key=f"actual_simple_other_cost_yen_{selected_id}",
                    )
                actual_repair_cost_yen = 0.0
                actual_parts_cost_yen = 0.0
                actual_overseas_fee_yen = 0.0
                actual_copy_cost_yen = 0.0
                actual_packaging_yen = 0.0
                actual_base_shipping_yen = actual_shipping_yen
                actual_fuel_surcharge_yen = 0.0
                actual_additional_fee_yen = 0.0
                actual_zonos_fee_yen = 0.0
                actual_duty_yen = 0.0
            else:
                cost_col1, cost_col2, cost_col3, cost_col4 = st.columns(4)
                actual_purchase_price_yen = cost_col1.number_input(
                    TEXT["actual_purchase_price_yen"],
                    min_value=0.0,
                    value=detail_defaults["actual_purchase_price_yen"],
                    step=100.0,
                    format="%.0f",
                    key=(
                        f"actual_purchase_price_yen_{selected_id}_"
                        f"{actual_purchase_default_suffix}"
                    ),
                )
                actual_overseas_fee_yen = cost_col2.number_input(
                    TEXT["actual_overseas_fee_yen"],
                    min_value=0.0,
                    value=detail_defaults["actual_overseas_fee_yen"],
                    step=10.0,
                    format="%.0f",
                    key=f"actual_overseas_fee_yen_{selected_id}",
                )
                actual_copy_cost_yen = cost_col3.number_input(
                    TEXT["actual_copy_cost_yen"],
                    min_value=0.0,
                    value=detail_defaults["actual_copy_cost_yen"],
                    step=10.0,
                    format="%.0f",
                    key=f"actual_copy_cost_yen_{selected_id}",
                )
                actual_packaging_yen = cost_col4.number_input(
                    TEXT["actual_packaging_yen"],
                    min_value=0.0,
                    value=detail_defaults["actual_packaging_yen"],
                    step=10.0,
                    format="%.0f",
                    key=f"actual_packaging_yen_{selected_id}",
                )
                other_col1, other_col2, other_col3, other_col4 = st.columns(4)
                actual_other_cost_yen = other_col1.number_input(
                    TEXT["actual_other_cost_yen"],
                    min_value=0.0,
                    value=detail_defaults["actual_other_cost_yen"],
                    step=10.0,
                    format="%.0f",
                    key=f"actual_other_cost_yen_{selected_id}",
                )
                actual_base_shipping_yen = other_col2.number_input(
                    TEXT["actual_base_shipping_yen"],
                    min_value=0.0,
                    value=detail_defaults["actual_base_shipping_yen"],
                    step=10.0,
                    format="%.0f",
                    key=f"actual_base_shipping_yen_{selected_id}",
                )
                actual_fuel_surcharge_yen = other_col3.number_input(
                    TEXT["actual_fuel_surcharge_yen"],
                    min_value=0.0,
                    value=detail_defaults["actual_fuel_surcharge_yen"],
                    step=10.0,
                    format="%.0f",
                    key=f"actual_fuel_surcharge_yen_{selected_id}",
                )
                actual_additional_fee_yen = other_col4.number_input(
                    TEXT["actual_additional_fee_yen"],
                    min_value=0.0,
                    value=detail_defaults["actual_additional_fee_yen"],
                    step=10.0,
                    format="%.0f",
                    key=f"actual_additional_fee_yen_{selected_id}",
                )
                zonos_col1, zonos_col2 = st.columns(2)
                actual_zonos_fee_yen = zonos_col1.number_input(
                    TEXT["actual_zonos_fee_yen"],
                    min_value=0.0,
                    value=detail_defaults["actual_zonos_fee_yen"],
                    step=10.0,
                    format="%.0f",
                    key=f"actual_zonos_fee_yen_{selected_id}",
                )
                actual_duty_yen = zonos_col2.number_input(
                    TEXT["actual_duty_yen"],
                    min_value=0.0,
                    value=detail_defaults["actual_duty_yen"],
                    step=10.0,
                    format="%.0f",
                    key=f"actual_duty_yen_{selected_id}",
                )
                actual_sales_fee_yen = None
                actual_repair_cost_yen = None
                actual_parts_cost_yen = None
        actual_details = {
            "actual_exchange_rate": actual_exchange_rate,
            "actual_usd_jpy_rate": actual_usd_jpy_rate_value,
            "actual_order_revenue_yen": actual_order_revenue_yen,
            "actual_purchase_price_yen": actual_purchase_price_yen,
            "actual_overseas_fee_yen": actual_overseas_fee_yen,
            "actual_copy_cost_yen": actual_copy_cost_yen,
            "actual_packaging_yen": actual_packaging_yen,
            "actual_other_cost_yen": actual_other_cost_yen,
            "actual_base_shipping_yen": actual_base_shipping_yen,
            "actual_fuel_surcharge_yen": actual_fuel_surcharge_yen,
            "actual_zonos_fee_yen": actual_zonos_fee_yen,
            "actual_duty_yen": actual_duty_yen,
            "actual_additional_fee_yen": actual_additional_fee_yen,
            "actual_sales_fee_yen": actual_sales_fee_yen,
            "actual_repair_cost_yen": actual_repair_cost_yen,
            "actual_parts_cost_yen": actual_parts_cost_yen,
        }
        if is_simple_profit_platform(draft_selected):
            effective_ebay_fee_rate = None
            effective_ad_fee_rate = None
        else:
            effective_ebay_fee_rate, effective_ad_fee_rate = calculate_effective_rates(
                actual_sale_price_usd,
                actual_ebay_fee_usd,
                actual_ad_fee_usd,
                actual_fixed_fee_usd,
                actual_exchange_rate,
                actual_usd_jpy_rate_value,
            )
        actual_profit_yen = calculate_actual_profit(
            draft_selected,
            actual_exchange_rate,
            actual_sale_price_usd,
            actual_buyer_shipping_usd,
            actual_ebay_fee_usd,
            actual_ad_fee_usd,
            actual_fixed_fee_usd,
            actual_usd_jpy_rate_value,
            actual_shipping_yen,
            actual_details,
        )
        actual_profit_margin = calculate_actual_profit_margin(
            draft_selected,
            actual_profit_yen,
            actual_sale_price_usd,
            actual_buyer_shipping_usd,
            actual_exchange_rate,
        )
        metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
        if is_simple_profit_platform(draft_selected):
            if platform_value(draft_selected) == PLATFORM_IPHONE_RESALE:
                metric_col1.metric("実際の仕入れ価格", yen(actual_purchase_price_yen))
            else:
                metric_col1.metric("実際の販売手数料", yen(actual_sales_fee_yen))
            metric_col2.metric("実際の送料", yen(actual_shipping_yen))
        else:
            metric_col1.metric(
                TEXT["effective_ebay_fee_rate"],
                "-" if effective_ebay_fee_rate is None else f"{effective_ebay_fee_rate:.2f}%",
            )
            metric_col2.metric(
                TEXT["effective_ad_fee_rate"],
                "-" if effective_ad_fee_rate is None else f"{effective_ad_fee_rate:.2f}%",
            )
        metric_col3.metric(TEXT["actual_profit_auto"], yen(actual_profit_yen))
        metric_col4.metric(
            TEXT["actual_profit_margin"],
            "-" if actual_profit_margin is None else f"{actual_profit_margin:.2f}%",
        )
        profit_key_suffix = (
            f"{actual_sale_price_usd:.2f}_{actual_buyer_shipping_usd:.2f}_"
            f"{actual_ebay_fee_usd:.2f}_{actual_ad_fee_usd:.2f}_"
            f"{actual_shipping_yen:.0f}_"
            f"{value(draft_selected, 'purchase_price_yen', 'purchase_price'):.0f}_"
            f"{value(draft_selected, 'domestic_shipping_yen'):.0f}_"
            f"{value(draft_selected, 'packaging_yen'):.0f}_"
            f"{value(draft_selected, 'other_cost_yen'):.0f}_"
            f"{value(draft_selected, 'exchange_spread_rate'):.2f}_"
            f"{value(draft_selected, 'fixed_fee_usd'):.2f}"
            f"_{actual_exchange_rate:.4f}_{actual_purchase_price_yen:.0f}"
            f"_{actual_usd_jpy_rate_value:.4f}"
            f"_{actual_overseas_fee_yen:.0f}_{actual_copy_cost_yen:.0f}"
            f"_{actual_packaging_yen:.0f}_{actual_other_cost_yen:.0f}"
            f"_{float(actual_sales_fee_yen or 0):.0f}"
            f"_{float(actual_repair_cost_yen or 0):.0f}"
            f"_{float(actual_parts_cost_yen or 0):.0f}"
        )
        actual_profit_key_prefix = (
            "simple_actual_profit_yen"
            if is_simple_profit_platform(draft_selected)
            else "actual_profit_yen"
        )
        actual_profit_yen = st.number_input(
            TEXT["actual_profit_save"],
            value=float(actual_profit_yen),
            step=100.0,
            format="%.0f",
            key=f"{actual_profit_key_prefix}_{selected_id}_{profit_key_suffix}",
        )
        actual_profit_margin = calculate_actual_profit_margin(
            draft_selected,
            actual_profit_yen,
            actual_sale_price_usd,
            actual_buyer_shipping_usd,
            actual_exchange_rate,
        )
    col1, col2, col3 = st.columns([1, 1, 1])
    if col1.button(TEXT["update"], type="primary"):
        update_listing_details(int(selected_id), edit_updates)
        update_status(
            int(selected_id),
            status,
            actual_sale_price_usd,
            actual_buyer_shipping_usd,
            actual_ebay_fee_usd,
            actual_ad_fee_usd,
            actual_fixed_fee_usd,
            effective_ebay_fee_rate,
            effective_ad_fee_rate,
            actual_shipping_yen,
            shipping_carrier,
            shipping_service,
            shipping_weight_g,
            actual_profit_yen,
            actual_profit_margin,
            sold_date.isoformat() if sold_date else None,
            actual_details,
        )
        close_management_editor_after_update(status)
        st.success(TEXT["updated"])
        st.rerun()

    if col2.button(TEXT["duplicate"], key=f"duplicate_selected_{selected_id}"):
        new_id = duplicate_listing(int(selected_id))
        st.session_state.selected_listing_id = new_id
        st.session_state.duplicated_listing_id = new_id
        st.success(TEXT["duplicated"])
        st.rerun()

    if col3.button(TEXT["delete"]):
        delete_listing(int(selected_id))
        st.success(TEXT["deleted"])
        st.rerun()


def main() -> None:
    render_header()
    init_db()
    render_registration_event_watcher()
    registration_notice = st.session_state.pop("registration_refresh_notice", None)
    if isinstance(registration_notice, dict):
        st.toast(
            f"利益計算ツールから「{registration_notice.get('product_name', '')}」を"
            f"登録しました。ID: {registration_notice.get('listing_id', '-')}"
        )
    exchange_rate = read_shared_exchange_rate() or 150.0
    rows = fetch_listings()
    management_tab, analytics_tab, variance_tab = st.tabs(
        ("出品管理", "分析・集計", "予定と実績の差額分析")
    )
    with management_tab:
        render_dashboard()
        st.divider()
        render_management(rows, exchange_rate)
    with analytics_tab:
        render_analytics(rows)
    with variance_tab:
        render_variance_analytics(rows)


if __name__ == "__main__":
    main()
