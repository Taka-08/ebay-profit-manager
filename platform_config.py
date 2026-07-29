from __future__ import annotations

from dataclasses import dataclass


PLATFORM_EBAY = "eBay"
PLATFORM_MERCARI = "\u30e1\u30eb\u30ab\u30ea"
PLATFORM_IPHONE_RESALE = "iPhone\u8ee2\u58f2"
PLATFORM_OPTIONS = (
    PLATFORM_EBAY,
    PLATFORM_MERCARI,
    PLATFORM_IPHONE_RESALE,
)

LEGACY_IPHONE_PLATFORM_VALUES = {
    "\u305d\u306e\u4ed6",
    "Yahoo!\u30d5\u30ea\u30de",
    "\u30e9\u30af\u30de",
    "Amazon",
}

FEE_MODE_RATE = "rate"
FEE_MODE_AMOUNT = "amount"
FEE_MODE_OPTIONS = (FEE_MODE_RATE, FEE_MODE_AMOUNT)


@dataclass(frozen=True)
class SimpleProfitCalculation:
    sales_fee_yen: float
    profit_yen: float
    profit_margin: float
    roi: float | None


def normalize_platform(value: object) -> str:
    text = str(value or PLATFORM_EBAY).strip()
    if text in PLATFORM_OPTIONS:
        return text
    if text in LEGACY_IPHONE_PLATFORM_VALUES:
        return PLATFORM_IPHONE_RESALE
    return PLATFORM_IPHONE_RESALE


def is_simple_platform(value: object) -> bool:
    return normalize_platform(value) in (
        PLATFORM_MERCARI,
        PLATFORM_IPHONE_RESALE,
    )


def calculate_simple_profit(
    *,
    platform: str,
    sale_price_yen: float,
    purchase_price_yen: float,
    fee_mode: str,
    fee_rate_percent: float,
    fee_amount_yen: float,
    shipping_yen: float,
    other_cost_yen: float,
    repair_cost_yen: float = 0.0,
    parts_cost_yen: float = 0.0,
) -> SimpleProfitCalculation:
    normalized = normalize_platform(platform)
    if normalized not in (PLATFORM_MERCARI, PLATFORM_IPHONE_RESALE):
        raise ValueError("Simple profit calculation is only available for domestic platforms.")
    if fee_mode not in FEE_MODE_OPTIONS:
        raise ValueError("Unsupported sales fee input mode.")

    sale = max(0.0, float(sale_price_yen))
    purchase = max(0.0, float(purchase_price_yen))
    shipping = max(0.0, float(shipping_yen))
    other = max(0.0, float(other_cost_yen))
    repair = max(0.0, float(repair_cost_yen))
    parts = max(0.0, float(parts_cost_yen))
    if normalized == PLATFORM_IPHONE_RESALE:
        sales_fee = 0.0
        profit = sale - purchase - shipping
        total_investment = purchase
    else:
        if fee_mode == FEE_MODE_RATE:
            sales_fee = sale * max(0.0, float(fee_rate_percent)) / 100
        else:
            sales_fee = max(0.0, float(fee_amount_yen))
        profit = sale - purchase - sales_fee - shipping - other
        total_investment = purchase + repair + parts

    margin = profit / sale * 100 if sale > 0 else 0.0
    roi = profit / total_investment * 100 if total_investment > 0 else None
    return SimpleProfitCalculation(
        sales_fee_yen=sales_fee,
        profit_yen=profit,
        profit_margin=margin,
        roi=roi,
    )
