"""Versioned cPass / SpeedPAK Economy fee calculations.

The transport rate itself comes from the official Ship via FedEx FICP table in
``shipping_rates.json``.  This module keeps cPass-specific U.S. DDP fees and
observed variable values separate from that official base table.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path
from typing import Any

from us_tariff import USDutyCalculation, calculate_us_duty_amount


CONFIG_PATH = Path(__file__).with_name("cpass_speedpak_economy_config.json")


@dataclass(frozen=True)
class CPassConditionalCharges:
    amount_yen: float
    labels: tuple[str, ...]
    minimum_billing_weight_g: float


@dataclass(frozen=True)
class CPassShippingBreakdown:
    published_base_transport_yen: float
    base_transport_yen: float
    transport_adjustment_rate_percent: float
    fuel_surcharge_yen: float
    import_clearance_fee_yen: float
    estimated_duty_tax_yen: float
    duty_processing_fee_yen: float
    conditional_surcharge_yen: float
    total_shipping_yen: float
    declared_value_foreign: float
    declared_currency: str
    quantity: int
    hts_code: str
    incoterm: str
    fuel_surcharge_rate_percent: float
    duty_processing_rate_percent: float
    profile_name: str
    profile_version: str
    effective_from: str
    calculated_at: str
    tariff: USDutyCalculation
    conditional_charge_labels: tuple[str, ...] = ()


@lru_cache(maxsize=4)
def load_cpass_config(path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config.get("profiles"), list) or not config["profiles"]:
        raise ValueError("cPass SpeedPAK Economy profiles are missing.")
    return config


def active_cpass_profile(
    destination_country: str,
    rule_date: str | date | datetime | None,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    source = config or load_cpass_config()
    applied_on = _parse_date(rule_date)
    candidates: list[tuple[date, dict[str, Any]]] = []
    for profile in source.get("profiles", []):
        if str(profile.get("destination_country") or "").upper() != destination_country.upper():
            continue
        effective_from = _parse_date(profile.get("effective_from"))
        effective_to_raw = str(profile.get("effective_to") or "")
        effective_to = _parse_date(effective_to_raw) if effective_to_raw else None
        if effective_from <= applied_on and (effective_to is None or applied_on <= effective_to):
            candidates.append((effective_from, profile))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def effective_declared_value(
    sale_price_foreign: float,
    declared_unit_price_foreign: float,
    quantity: int,
    declared_total_value_foreign: float,
) -> float:
    if declared_total_value_foreign > 0:
        return float(declared_total_value_foreign)
    if declared_unit_price_foreign > 0:
        return float(declared_unit_price_foreign) * max(int(quantity), 1)
    return float(sale_price_foreign)


def rounded_package_dimensions_cm(
    length_cm: float,
    width_cm: float,
    height_cm: float,
) -> tuple[float, float, float]:
    return tuple(float(math.ceil(value)) for value in (length_cm, width_cm, height_cm))


def calculate_conditional_charges(
    profile: dict[str, Any],
    *,
    length_cm: float,
    width_cm: float,
    height_cm: float,
    actual_weight_g: float,
) -> CPassConditionalCharges:
    rules = profile.get("conditional_surcharges") or {}
    if min(length_cm, width_cm, height_cm) <= 0:
        return CPassConditionalCharges(0.0, (), 0.0)

    dimensions = sorted(rounded_package_dimensions_cm(length_cm, width_cm, height_cm), reverse=True)
    longest, second, shortest = dimensions
    length_plus_girth = longest + 2 * (second + shortest)
    volume_cm3 = length_cm * width_cm * height_cm
    labels: list[str] = []
    charges: list[float] = []
    minimum_billing_weight_g = 0.0

    out_of_gauge = rules.get("out_of_gauge") or {}
    if (
        longest > float(out_of_gauge.get("any_dimension_over_cm") or math.inf)
        or volume_cm3 > float(out_of_gauge.get("volume_over_cm3") or math.inf)
    ):
        labels.append("規定外貨物手数料（寸法）")
        charges.append(float(out_of_gauge.get("fee_yen") or 0))

    oversize = rules.get("oversize") or {}
    if (
        longest > float(oversize.get("longest_over_cm") or math.inf)
        or length_plus_girth > float(oversize.get("length_plus_girth_over_cm") or math.inf)
    ):
        labels.append("オーバーサイズ料金")
        charges.append(float(oversize.get("fee_yen") or 0))
        minimum_billing_weight_g = max(
            minimum_billing_weight_g,
            float(oversize.get("minimum_billing_weight_g") or 0),
        )

    handling = rules.get("additional_handling") or {}
    dimension_rule = handling.get("dimension") or {}
    dimension_applies = (
        longest > float(dimension_rule.get("longest_over_cm") or math.inf)
        or second > float(dimension_rule.get("second_longest_over_cm") or math.inf)
        or length_plus_girth > float(dimension_rule.get("length_plus_girth_over_cm") or math.inf)
    )
    weight_rule = handling.get("weight") or {}
    weight_applies = actual_weight_g > float(weight_rule.get("actual_weight_over_g") or math.inf)
    if dimension_applies or weight_applies:
        labels.append("特別取扱料金")
        charges.append(float(handling.get("fee_yen") or 0))
        if dimension_applies:
            minimum_billing_weight_g = max(
                minimum_billing_weight_g,
                float(dimension_rule.get("minimum_billing_weight_g") or 0),
            )

    # The guide says that only the highest additional-handling charge applies.
    # Oversize and handling are therefore not stacked by this estimator.
    return CPassConditionalCharges(
        amount_yen=max(charges, default=0.0),
        labels=tuple(labels),
        minimum_billing_weight_g=minimum_billing_weight_g,
    )


def calculate_cpass_shipping_breakdown(
    *,
    profile: dict[str, Any],
    published_base_transport_yen: float,
    declared_value_foreign: float,
    declared_currency: str,
    exchange_rate: float,
    quantity: int,
    country_of_origin: str,
    mfn_rate_percent: float,
    rule_date: str | date | datetime | None,
    hts_code: str,
    incoterm: str,
    conditional_surcharge_yen: float = 0.0,
    conditional_charge_labels: tuple[str, ...] = (),
) -> CPassShippingBreakdown:
    fees = profile.get("fees") or {}
    fuel = fees.get("fuel_surcharge") or {}
    import_clearance = fees.get("import_clearance") or {}
    duty_processing = fees.get("duty_processing") or {}
    transport_adjustment = profile.get("transport_adjustment") or {}

    tariff = calculate_us_duty_amount(
        country_of_origin=country_of_origin,
        mfn_rate_percent=mfn_rate_percent,
        product_price=declared_value_foreign,
        exchange_rate=exchange_rate,
        rule_date=rule_date,
    )
    transport_multiplier = float(transport_adjustment.get("multiplier") or 1)
    base_transport_yen = round_half_up(published_base_transport_yen * transport_multiplier)
    adjustment_rate = (transport_multiplier - 1) * 100
    fuel_rate = float(fuel.get("rate_percent") or 0)
    fuel_yen = round_half_up(base_transport_yen * fuel_rate / 100)
    clearance_yen = float(import_clearance.get("amount_yen") or 0)
    duty_yen = float(tariff.duty_amount_yen)
    processing_rate = float(duty_processing.get("rate_percent") or 0)
    processing_yen = round_half_up(duty_yen * processing_rate / 100)
    total = (
        float(base_transport_yen)
        + fuel_yen
        + clearance_yen
        + duty_yen
        + processing_yen
        + float(conditional_surcharge_yen)
    )
    return CPassShippingBreakdown(
        published_base_transport_yen=float(published_base_transport_yen),
        base_transport_yen=float(base_transport_yen),
        transport_adjustment_rate_percent=adjustment_rate,
        fuel_surcharge_yen=fuel_yen,
        import_clearance_fee_yen=clearance_yen,
        estimated_duty_tax_yen=duty_yen,
        duty_processing_fee_yen=processing_yen,
        conditional_surcharge_yen=float(conditional_surcharge_yen),
        total_shipping_yen=total,
        declared_value_foreign=float(declared_value_foreign),
        declared_currency=str(declared_currency).upper(),
        quantity=max(int(quantity), 1),
        hts_code=str(hts_code or "").strip(),
        incoterm=str(incoterm or "DDP"),
        fuel_surcharge_rate_percent=fuel_rate,
        duty_processing_rate_percent=processing_rate,
        profile_name=str(profile.get("name") or ""),
        profile_version=str(profile.get("version") or ""),
        effective_from=str(profile.get("effective_from") or ""),
        calculated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        tariff=tariff,
        conditional_charge_labels=tuple(conditional_charge_labels),
    )


def round_half_up(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _parse_date(value: str | date | datetime | None) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value:
        return date.fromisoformat(str(value)[:10])
    return date.today()
