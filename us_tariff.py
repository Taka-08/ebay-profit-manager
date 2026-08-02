"""Versioned U.S. duty estimation used by the profit calculator."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path
from typing import Any


RULES_PATH = Path(__file__).with_name("us_tariff_rules.json")
UNSPECIFIED_ORIGIN = ""
UNSPECIFIED_ORIGIN_LABEL = "Unspecified (legacy 10% compatibility)"


@dataclass(frozen=True)
class USTariffRateResult:
    country_of_origin: str
    mfn_rate_percent: float
    estimated_rate_percent: float | None
    applied_rate_percent: float
    rule_name: str
    rule_version: str
    rule_effective_date: str
    rule_applied_date: str
    taxable_base_type: str
    legacy_compatibility: bool
    additional_duties: tuple[Any, ...] = ()
    exemptions: tuple[Any, ...] = ()
    special_tariffs: tuple[Any, ...] = ()


@dataclass(frozen=True)
class USDutyCalculation:
    rate: USTariffRateResult
    product_price_yen: float
    taxable_base_yen: float
    unrounded_duty_amount_yen: float
    duty_amount_yen: float
    calculated_at: str


@lru_cache(maxsize=4)
def load_us_tariff_config(path: str | Path = RULES_PATH) -> dict[str, Any]:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config.get("origins"), dict):
        raise ValueError("U.S. tariff origin master is missing.")
    if not isinstance(config.get("rules"), list) or not config["rules"]:
        raise ValueError("U.S. tariff rules are missing.")
    return config


def supported_origins(config: dict[str, Any] | None = None) -> tuple[str, ...]:
    source = config or load_us_tariff_config()
    return tuple(str(code) for code in source["origins"])


def origin_label(origin: str, config: dict[str, Any] | None = None) -> str:
    if not str(origin or "").strip():
        return UNSPECIFIED_ORIGIN_LABEL
    source = config or load_us_tariff_config()
    code = normalize_origin(origin, source)
    return str(source["origins"].get(code, source["origins"]["Others"]))


def normalize_origin(origin: str, config: dict[str, Any] | None = None) -> str:
    raw = str(origin or "").strip()
    if not raw:
        return UNSPECIFIED_ORIGIN
    if raw.casefold() == "others":
        return "Others"
    code = raw.upper()
    source = config or load_us_tariff_config()
    if code in source["origins"]:
        return code
    return "Others"


def parse_rule_date(value: str | date | datetime | None) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value:
        return date.fromisoformat(str(value)[:10])
    return date.today()


def _active_rule(config: dict[str, Any], applied_on: date) -> dict[str, Any] | None:
    candidates: list[tuple[date, dict[str, Any]]] = []
    for rule in config.get("rules", []):
        effective_from = parse_rule_date(rule.get("effective_from"))
        effective_to_raw = str(rule.get("effective_to") or "")
        effective_to = parse_rule_date(effective_to_raw) if effective_to_raw else None
        if effective_from <= applied_on and (effective_to is None or applied_on <= effective_to):
            candidates.append((effective_from, rule))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def calculate_us_tariff_rate(
    country_of_origin: str,
    mfn_rate_percent: float,
    rule_date: str | date | datetime | None,
    *,
    legacy_rate_percent: float | None = None,
    config: dict[str, Any] | None = None,
) -> USTariffRateResult:
    """Determine the estimated U.S. duty rate without shipping-service fees."""
    source = config or load_us_tariff_config()
    origin = normalize_origin(country_of_origin, source)
    mfn_rate = float(mfn_rate_percent or 0)
    if mfn_rate < 0:
        raise ValueError("MFN rate must be zero or greater.")
    applied_on = parse_rule_date(rule_date)
    rule = _active_rule(source, applied_on)

    if not origin or rule is None:
        legacy = source["legacy_rule"]
        rate = float(
            legacy_rate_percent
            if legacy_rate_percent is not None
            else legacy.get("rate_percent", 10.0)
        )
        return USTariffRateResult(
            country_of_origin=origin,
            mfn_rate_percent=mfn_rate,
            estimated_rate_percent=None,
            applied_rate_percent=rate,
            rule_name=str(legacy.get("name") or "Legacy U.S. duty compatibility"),
            rule_version=str(legacy.get("version") or "legacy"),
            rule_effective_date="",
            rule_applied_date=applied_on.isoformat(),
            taxable_base_type=str(legacy.get("taxable_base") or "product_price_jpy"),
            legacy_compatibility=True,
            additional_duties=tuple(legacy.get("additional_duties") or ()),
            exemptions=tuple(legacy.get("exemptions") or ()),
            special_tariffs=tuple(legacy.get("special_tariffs") or ()),
        )

    rates = rule.get("origin_rates_percent") or {}
    estimated_rate = float(rates.get(origin, rates["Others"]))
    origin_rules = rule.get("origin_rules") or {}
    mode = str(origin_rules.get(origin) or origin_rules.get("default") or "estimated_ratio")
    applied_rate = max(mfn_rate, estimated_rate) if mode == "max_mfn_or_estimated_ratio" else estimated_rate
    return USTariffRateResult(
        country_of_origin=origin,
        mfn_rate_percent=mfn_rate,
        estimated_rate_percent=estimated_rate,
        applied_rate_percent=applied_rate,
        rule_name=str(rule.get("name") or "U.S. duty estimate"),
        rule_version=str(rule.get("version") or ""),
        rule_effective_date=str(rule.get("effective_from") or ""),
        rule_applied_date=applied_on.isoformat(),
        taxable_base_type=str(rule.get("taxable_base") or "product_price_jpy"),
        legacy_compatibility=False,
        additional_duties=tuple(rule.get("additional_duties") or ()),
        exemptions=tuple(rule.get("exemptions") or ()),
        special_tariffs=tuple(rule.get("special_tariffs") or ()),
    )


def calculate_us_duty_base_yen(product_price: float, exchange_rate: float) -> float:
    """Keep the current taxable base: product price only, converted to JPY."""
    return float(Decimal(str(product_price)) * Decimal(str(exchange_rate)))


def calculate_us_duty_amount(
    country_of_origin: str,
    mfn_rate_percent: float,
    product_price: float,
    exchange_rate: float,
    rule_date: str | date | datetime | None,
    *,
    legacy_rate_percent: float | None = None,
    config: dict[str, Any] | None = None,
) -> USDutyCalculation:
    rate = calculate_us_tariff_rate(
        country_of_origin,
        mfn_rate_percent,
        rule_date,
        legacy_rate_percent=legacy_rate_percent,
        config=config,
    )
    product_price_yen = calculate_us_duty_base_yen(product_price, exchange_rate)
    taxable_base_yen = product_price_yen
    unrounded_duty = (
        Decimal(str(taxable_base_yen))
        * Decimal(str(rate.applied_rate_percent))
        / Decimal("100")
    )
    duty = unrounded_duty.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return USDutyCalculation(
        rate=rate,
        product_price_yen=product_price_yen,
        taxable_base_yen=taxable_base_yen,
        unrounded_duty_amount_yen=float(unrounded_duty),
        duty_amount_yen=float(duty),
        calculated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
