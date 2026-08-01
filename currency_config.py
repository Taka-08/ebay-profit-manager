from __future__ import annotations


DEFAULT_CURRENCY = "USD"
SUPPORTED_CURRENCIES = ("USD", "CAD", "GBP", "AUD")

CURRENCY_NAMES = {
    "USD": "米ドル",
    "CAD": "カナダドル",
    "GBP": "イギリスポンド",
    "AUD": "オーストラリアドル",
}

CURRENCY_SYMBOLS = {
    "USD": "$",
    "CAD": "C$",
    "GBP": "£",
    "AUD": "A$",
}

DEFAULT_JPY_RATES = {
    "USD": 150.0,
    "CAD": 110.0,
    "GBP": 190.0,
    "AUD": 100.0,
}

YAHOO_FINANCE_SYMBOLS = {
    "USD": "JPY=X",
    "CAD": "CADJPY=X",
    "GBP": "GBPJPY=X",
    "AUD": "AUDJPY=X",
}


def normalize_currency(value: object) -> str:
    currency = str(value or DEFAULT_CURRENCY).strip().upper()
    return currency if currency in SUPPORTED_CURRENCIES else DEFAULT_CURRENCY


def currency_symbol(currency: object) -> str:
    return CURRENCY_SYMBOLS[normalize_currency(currency)]


def currency_name(currency: object) -> str:
    return CURRENCY_NAMES[normalize_currency(currency)]


def currency_option_label(currency: object) -> str:
    code = normalize_currency(currency)
    return f"{code}：{CURRENCY_NAMES[code]}（{CURRENCY_SYMBOLS[code]}）"


def currency_amount(value: float | int, currency: object) -> str:
    return f"{currency_symbol(currency)}{float(value):,.2f}"
