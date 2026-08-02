from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pdfplumber


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from destination_countries import (  # noqa: E402
    DEFAULT_DESTINATION_COUNTRY_CODES,
    EU27_COUNTRY_CODES,
    normalize_destination_country,
)


DOWNLOADS_DIR = Path.home() / "Downloads"
OUTPUT_PATH = ROOT_DIR / "shipping_rates.json"
JAPAN_POST_DATA_PATH = Path(__file__).with_name("japan_post_2026_06_manual_extract.json")

PDF_PATHS = {
    "japan_post": DOWNLOADS_DIR / "charges.pdf",
    "orange": DOWNLOADS_DIR / "1184103658011230208.pdf",
    "dhl": DOWNLOADS_DIR / "RATE GUIDE of eBay SpeedPAK Japan Ship via DHL-JP (1).pdf",
    "fedex": (
        DOWNLOADS_DIR / "最新2.pdf"
        if (DOWNLOADS_DIR / "最新2.pdf").exists()
        else DOWNLOADS_DIR / "RATE GUIDE of eBay SpeedPAK Japan Ship via FedEx-JP (1).pdf"
    ),
}

COMMON_COUNTRIES = ["US", "CA", "GB", "AU", "DE", "FR"]

ORANGE_EFFECTIVE_FROM = "2026-07-30"
ORANGE_RATE_BOOK_VERSION = "orange-connex-economy-japan-2026-07-30"
FEDEX_EFFECTIVE_FROM = "2026-05-08"
FEDEX_RATE_BOOK_VERSION = "speedpak-ship-via-fedex-2026-05-08"
ORANGE_EU_TABLE_COUNTRIES = (
    "DE",
    "AT",
    "BE",
    "BG",
    "CY",
    "CZ",
    "DK",
    "EE",
    "ES",
    "FI",
    "FR",
    "GR",
    "HR",
    "HU",
    "IE",
    "IT",
    "LT",
    "LU",
    "LV",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SE",
    "SI",
    "SK",
)

ORANGE_US_NON_MAINLAND_PREFIXES = {
    "006", "007", "008", "009", "967", "968", "969", "995", "996", "997",
    "998", "999", "090", "091", "092", "093", "094", "095", "096", "097",
    "098", "099", "340", "962", "963", "964", "965", "966",
}

FEDEX_US_WEST_RANGES = [
    (83200, 83999),
    (84000, 84799),
    (85000, 86599),
    (89000, 89899),
    (90000, 96699),
    (97000, 97999),
    (98000, 99499),
]


def parse_money(value: str) -> int:
    return int(value.replace(",", "").strip())


def parse_float(value: str) -> float:
    return float(value.replace(",", "").strip())


def add_rate_rows(
    rows: list[dict[str, Any]],
    zone: str,
    weights_to_prices: list[tuple[float, int]],
    *,
    source_page: int | None = None,
) -> None:
    previous_max = 0.0
    for weight_kg, price in sorted(weights_to_prices):
        max_weight_g = round(weight_kg * 1000)
        row = {
            "zone": zone,
            "min_weight_g": previous_max + 0.0001,
            "max_weight_g": max_weight_g,
            "base_shipping_yen": price,
        }
        if source_page is not None:
            row["source_page"] = source_page
        rows.append(row)
        previous_max = max_weight_g


def rows_from_weights_and_prices(weights_g: list[float], prices: list[int], zone: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    previous_max = 0.0
    for weight_g, price in zip(weights_g, prices):
        rows.append(
            {
                "zone": zone,
                "min_weight_g": previous_max + 0.0001,
                "max_weight_g": float(weight_g),
                "base_shipping_yen": int(price),
            }
        )
        previous_max = float(weight_g)
    return rows


def parse_orange_rate_table(pdf: pdfplumber.PDF, page_number: int) -> list[tuple[float, int]]:
    table = pdf.pages[page_number - 1].extract_tables()[0]
    rates: list[tuple[float, int]] = []
    for row in table:
        cells = [cell for cell in row if cell not in (None, "")]
        if not cells or "重量" in str(cells[0]):
            continue
        if len(cells) == 1:
            parts = re.findall(r"(?:\d{1,3},)+(?:\d{3})|\d+(?:\.\d+)?|\d+", str(cells[0]))
        else:
            parts = [str(cell) for cell in cells]
        for index in range(0, len(parts), 2):
            if index + 1 >= len(parts):
                continue
            try:
                rates.append((parse_float(parts[index]), parse_money(parts[index + 1])))
            except ValueError:
                continue
    return rates


def parse_orange_europe_rate_tables(
    pdf: pdfplumber.PDF,
    page_numbers: tuple[int, ...] = (12, 13),
) -> dict[str, list[tuple[float, int, int]]]:
    rates_by_country: dict[str, list[tuple[float, int, int]]] = {
        code: [] for code in ORANGE_EU_TABLE_COUNTRIES
    }
    weights: list[float] = []
    for page_number in page_numbers:
        tables = pdf.pages[page_number - 1].extract_tables()
        if len(tables) != 1:
            raise ValueError(f"Orange Connex EU page {page_number}: expected one table")
        table = tables[0]
        header = tuple(str(cell or "").strip() for cell in table[0][1:])
        if header != ORANGE_EU_TABLE_COUNTRIES:
            raise ValueError(
                f"Orange Connex EU page {page_number}: unexpected country columns {header}"
            )
        for row in table[1:]:
            if not row or not str(row[0] or "").strip():
                continue
            weight_kg = parse_float(str(row[0]))
            weights.append(weight_kg)
            for code, cell in zip(ORANGE_EU_TABLE_COUNTRIES, row[1:]):
                value = str(cell or "").strip()
                if not value:
                    continue
                rates_by_country[code].append(
                    (weight_kg, parse_money(value), page_number)
                )

    if len(weights) != 76 or weights[0] != 0.1 or weights[-1] != 30.0:
        raise ValueError(
            "Orange Connex EU table must contain 76 weight rows from 0.1kg to 30kg"
        )
    expected_counts = {
        code: 66 if code == "DE" else 56 if code == "SE" else 76
        for code in ORANGE_EU_TABLE_COUNTRIES
    }
    actual_counts = {code: len(rows) for code, rows in rates_by_country.items()}
    if actual_counts != expected_counts:
        raise ValueError(
            f"Orange Connex EU country rate counts differ: {actual_counts}"
        )
    return rates_by_country


def build_orange_services() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    zones = {
        "US_MAINLAND": {"page": 5, "country": "US"},
        "US_NON_MAINLAND": {"page": 6, "country": "US"},
        "UK": {"page": 9, "country": "GB"},
        "AU": {"page": 16, "country": "AU"},
    }
    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    with pdfplumber.open(PDF_PATHS["orange"]) as pdf:
        for zone, info in zones.items():
            parsed = parse_orange_rate_table(pdf, int(info["page"]))
            add_rate_rows(rows, zone, parsed, source_page=int(info["page"]))
            counts[zone] = len(parsed)
        europe_rates = parse_orange_europe_rate_tables(pdf)
        for country_code, country_rates in europe_rates.items():
            by_page: dict[int, list[tuple[float, int]]] = {}
            for weight_kg, price_yen, page_number in country_rates:
                by_page.setdefault(page_number, []).append((weight_kg, price_yen))
            previous_max_weight_g = 0.0
            for page_number in sorted(by_page):
                page_rows: list[dict[str, Any]] = []
                add_rate_rows(
                    page_rows,
                    country_code,
                    by_page[page_number],
                    source_page=page_number,
                )
                for row in page_rows:
                    row["min_weight_g"] = previous_max_weight_g + 0.0001
                    previous_max_weight_g = float(row["max_weight_g"])
                    rows.append(row)
            counts[country_code] = len(country_rates)

    eu_max_weights = {
        code: 25000 if code == "DE" else 20000 if code == "SE" else 30000
        for code in EU27_COUNTRY_CODES
    }
    eu_max_sizes = {
        code: {
            "length_cm": 120,
            "width_cm": 60 if code == "DE" else 40,
            "height_cm": 60 if code == "DE" else 40,
            "volume_cm3": 180000,
        }
        for code in EU27_COUNTRY_CODES
    }
    countries = ["US", "GB", "AU", *EU27_COUNTRY_CODES]
    country_zone_rules: dict[str, Any] = {
        "US": {
            "requires_postal_code": True,
            "default_zone": "US_MAINLAND",
            "postal_prefix_zones": [
                {
                    "prefixes": sorted(ORANGE_US_NON_MAINLAND_PREFIXES),
                    "zone": "US_NON_MAINLAND",
                }
            ],
        },
        "GB": "UK",
        "AU": "AU",
        **{code: code for code in EU27_COUNTRY_CODES},
    }

    service = {
        "carrier": "SpeedPAK / CPaSS",
        "service": "SpeedPAK Economy",
        "countries": countries,
        "country_zone_rules": country_zone_rules,
        "weight_basis": "greater",
        "volumetric_divisor_cm3_per_kg": 8000,
        "rounding_unit_g": 1,
        "max_weight_g": 25000,
        "max_weight_g_by_zone": {
            "US_MAINLAND": 25000,
            "US_NON_MAINLAND": 15000,
            "UK": 25000,
            "AU": 22500,
            **eu_max_weights,
        },
        "max_actual_weight_g_by_zone": {
            "UK": 15000,
            "AU": 22000,
        },
        "max_size_by_zone": {
            "US_MAINLAND": {"length_cm": 66, "length_plus_girth_cm": 274},
            "US_NON_MAINLAND": {"length_cm": 66, "length_plus_girth_cm": 274},
            "UK": {"length_cm": 120, "length_plus_girth_cm": 225},
            "AU": {"length_cm": 105, "volume_cm3": 180000},
            **eu_max_sizes,
        },
        "max_product_value_by_zone": {
            "US_MAINLAND": {"amount": 1300, "currency": "USD"},
            "US_NON_MAINLAND": {"amount": 1300, "currency": "USD"},
            "UK": {"amount": 135, "currency": "GBP"},
            "AU": {"amount": 1000, "currency": "AUD"},
            **{
                code: {"amount": 150, "currency": "EUR", "enforced": True}
                for code in EU27_COUNTRY_CODES
            },
        },
        "fuel_surcharge_rate": 0,
        "fuel_surcharge_status": "variable_not_included_in_base_rate",
        "surcharge_yen": 0,
        "additional_fee_yen": 0,
        "other_additional_fee_yen": 0,
        "source_pdf": str(PDF_PATHS["orange"]),
        "source_pages": [4, 5, 6, 9, 12, 13, 16],
        "rate_book_version": ORANGE_RATE_BOOK_VERSION,
        "effective_from": ORANGE_EFFECTIVE_FROM,
        "rates": rows,
    }
    metadata = {
        "rate_rows_by_zone": counts,
        "zones": len(zones) + len(EU27_COUNTRY_CODES),
        "countries": len(countries),
        "rate_count": len(rows),
        "effective_from": ORANGE_EFFECTIVE_FROM,
        "rate_book_version": ORANGE_RATE_BOOK_VERSION,
    }
    return [service], metadata


def build_unregistered_services() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    service_specs = [
        ("SpeedPAK / CPaSS", "SpeedPAK Standard", "registered placeholder"),
        ("SpeedPAK / CPaSS", "SpeedPAK Expedited", "registered placeholder"),
    ]
    services = []
    for carrier, service, note in service_specs:
        services.append(
            {
                "carrier": carrier,
                "service": service,
                "countries": COMMON_COUNTRIES,
                "country_zone_rules": {country: "ALL" for country in COMMON_COUNTRIES},
                "weight_basis": "actual",
                "rounding_unit_g": 1,
                "max_weight_g": 0,
                "fuel_surcharge_rate": 0,
                "surcharge_yen": 0,
                "additional_fee_yen": 0,
                "other_additional_fee_yen": 0,
                "source_pdf": "",
                "source_pages": [],
                "data_status": "unregistered",
                "note": note,
                "rates": [],
            }
        )
    return services, {"services": len(services), "rate_count": 0}


def build_japan_post_services() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = json.loads(JAPAN_POST_DATA_PATH.read_text(encoding="utf-8"))
    source_pdf = str(PDF_PATHS["japan_post"])
    country_zone_rules = {
        normalize_destination_country(country): zone
        for country, zone in data["ui_country_zone_rules"].items()
    }
    countries = list(country_zone_rules)
    services: list[dict[str, Any]] = []
    row_counts: dict[str, int] = {}
    rate_count = 0
    for service_data in data["services"]:
        weights = service_data["weights_g"]
        prices_by_zone = service_data["prices_by_zone"]
        rates: list[dict[str, Any]] = []
        for zone, prices in prices_by_zone.items():
            zone_rows = rows_from_weights_and_prices(weights, prices, zone)
            rates.extend(zone_rows)
            rate_count += len(zone_rows)
        row_counts[service_data["service"]] = len(weights)
        services.append(
            {
                "carrier": service_data["carrier"],
                "service": service_data["service"],
                "countries": countries,
                "country_zone_rules": country_zone_rules,
                "weight_basis": service_data["weight_basis"],
                "rounding_unit_g": service_data["rounding_unit_g"],
                "max_weight_g": service_data["max_weight_g"],
                "max_actual_weight_g": service_data["max_actual_weight_g"],
                "max_size": service_data.get("max_size", {}),
                "fuel_surcharge_rate": 0,
                "surcharge_yen": 0,
                "additional_fee_yen": 0,
                "other_additional_fee_yen": 0,
                "source_pdf": source_pdf,
                "source_pages": service_data["source_pages"],
                "note": service_data.get("note", ""),
                "rates": rates,
            }
        )
    metadata = {
        "services": len(services),
        "zones": len(data["zones"]),
        "countries": len(country_zone_rules),
        "weight_rows_by_service": row_counts,
        "rate_count": rate_count,
        "source_version": data["version"],
    }
    return services, metadata


def numeric_rate_lines(text: str, expected_values: int) -> list[tuple[float, list[int]]]:
    rows: list[tuple[float, list[int]]] = []
    pattern = re.compile(r"^(\d+(?:\.\d+)?)\s+(.+)$")
    for line in text.splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        numbers = re.findall(r"\d{1,3}(?:,\d{3})*|\d+", match.group(2))
        if len(numbers) != expected_values:
            continue
        rows.append((parse_float(match.group(1)), [parse_money(number) for number in numbers]))
    return rows


def build_zone_rates(zone_names: list[str], rows_by_weight: list[tuple[float, list[int]]]) -> list[dict[str, Any]]:
    rates: list[dict[str, Any]] = []
    by_zone = {zone: [] for zone in zone_names}
    for weight, values in rows_by_weight:
        for zone, price in zip(zone_names, values):
            by_zone[zone].append((weight, price))
    for zone, weights_to_prices in by_zone.items():
        add_rate_rows(rates, zone, weights_to_prices)
    return rates


def extract_dhl_package_rows() -> tuple[list[tuple[float, list[int]]], list[tuple[float, list[int]]]]:
    envelope_rows: list[tuple[float, list[int]]] = []
    package_rows: list[tuple[float, list[int]]] = []
    with pdfplumber.open(PDF_PATHS["dhl"]) as pdf:
        in_package = False
        in_envelope = False
        for page_number in range(12, 18):
            text = pdf.pages[page_number - 1].extract_text(x_tolerance=1, y_tolerance=2) or ""
            for line in text.splitlines():
                stripped = line.strip()
                if stripped == "Express Envelope":
                    in_envelope = True
                    in_package = False
                    continue
                if stripped.startswith("Express Worldwide") or stripped.startswith("書類"):
                    in_envelope = False
                    continue
                if stripped.startswith("荷物"):
                    in_envelope = False
                    in_package = True
                    continue
                parsed = numeric_rate_lines(stripped, 11)
                if not parsed:
                    continue
                if in_envelope:
                    envelope_rows.extend(parsed)
                    in_envelope = False
                elif in_package:
                    package_rows.extend(parsed)
    return envelope_rows, package_rows


def build_dhl_services() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    zones = [f"Zone {index}" for index in range(1, 12)]
    envelope_rows, package_rows = extract_dhl_package_rows()
    zone_rules = {
        "US": "Zone 10",
        "CA": "Zone 5",
        "GB": "Zone 5",
        "AU": "Zone 11",
        "DE": "Zone 2",
        "FR": "Zone 1",
    }
    common = list(zone_rules.keys())
    base = {
        "carrier": "DHL",
        "countries": common,
        "country_zone_rules": zone_rules,
        "source_pdf": str(PDF_PATHS["dhl"]),
        "source_pages": [4, 11, 12, 13, 14, 15, 16, 17, 24, 25],
        "fuel_surcharge_rate": 0,
        "surcharge_yen": 0,
        "other_additional_fee_yen": 0,
    }
    envelope = {
        **base,
        "service": "Express Envelope",
        "weight_basis": "actual",
        "rounding_unit_g": 1,
        "max_weight_g": 300,
        "max_actual_weight_g": 300,
        "max_size": {"length_cm": 32, "width_cm": 24, "height_cm": 1},
        "additional_fee_yen": 0,
        "rates": build_zone_rates(zones, envelope_rows),
    }
    worldwide_base = {
        **base,
        "weight_basis": "greater",
        "volumetric_divisor_cm3_per_kg": 5000,
        "rounding_unit_g": 1,
        "max_weight_g": 154000,
        "max_actual_weight_g": 70000,
        "max_size": {"length_cm": 120, "width_cm": 80, "height_cm": 80, "volumetric_weight_g": 153600},
        "rates": build_zone_rates(zones, package_rows),
    }
    services = [
        {**worldwide_base, "service": "Express Worldwide", "additional_fee_yen": 0},
        {**worldwide_base, "service": "Express 12:00", "additional_fee_yen": 636},
        {**worldwide_base, "service": "Express 10:30", "additional_fee_yen": 1485, "max_actual_weight_g": 30000},
        {**worldwide_base, "service": "Express 9:00", "additional_fee_yen": 3711, "max_actual_weight_g": 30000},
    ]
    metadata = {
        "rate_rows_envelope": len(envelope_rows),
        "rate_rows_worldwide": len(package_rows),
        "zones": len(zones),
        "countries_from_zone_table": count_country_codes(PDF_PATHS["dhl"], 11),
        "rate_count": len(envelope["rates"]) + sum(len(service["rates"]) for service in services),
    }
    return [envelope, *services], metadata


def extract_fedex_rows(page_numbers: list[int], zones: list[str]) -> list[tuple[float, list[int]]]:
    rows: list[tuple[float, list[int]]] = []
    with pdfplumber.open(PDF_PATHS["fedex"]) as pdf:
        for page_number in page_numbers:
            text = pdf.pages[page_number - 1].extract_text(x_tolerance=1, y_tolerance=2) or ""
            rows.extend(numeric_rate_lines(text, len(zones)))
    return rows


def extract_fedex_ip_rows(page_numbers: list[int], zones: list[str]) -> tuple[list[tuple[float, list[int]]], list[tuple[float, list[int]]], list[tuple[float, list[int]]]]:
    all_rows = extract_fedex_rows(page_numbers, zones)
    if not all_rows:
        return [], [], []
    envelope = all_rows[:1]
    pak = all_rows[1:6]
    package = all_rows[6:]
    return envelope, pak, package


def build_fedex_services() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    group1 = ["A", "D", "E", "F", "G", "H", "I", "J", "K", "M", "U"]
    group2 = ["N", "O", "Q", "R", "S", "T", "V", "W", "X", "Y", "Z"]
    zone_rules = {
        "US": {
            "requires_postal_code": True,
            "default_zone": "F",
            "postal_range_zones": [
                {"start": start, "end": end, "zone": "E"} for start, end in FEDEX_US_WEST_RANGES
            ],
        },
        "CA": "F",
        "GB": "M",
        "AU": "U",
        "DE": "M",
        "FR": "M",
    }
    common = list(zone_rules.keys())
    ficp_rows_group1 = extract_fedex_rows([13, 14, 15], group1)
    ficp_rows_group2 = extract_fedex_rows([16, 17, 18], group2)
    ficp_rates = build_zone_rates(group1, ficp_rows_group1) + build_zone_rates(group2, ficp_rows_group2)

    ip_env_1, ip_pak_1, ip_pkg_1 = extract_fedex_ip_rows([19, 20, 21], group1)
    ip_env_2, ip_pak_2, ip_pkg_2 = extract_fedex_ip_rows([22, 23, 24], group2)
    base = {
        "carrier": "FedEx",
        "countries": common,
        "country_zone_rules": zone_rules,
        "source_pdf": PDF_PATHS["fedex"].name,
        "source_pages": [4, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 37, 38],
        "effective_from": FEDEX_EFFECTIVE_FROM,
        "rate_book_version": FEDEX_RATE_BOOK_VERSION,
        "fuel_surcharge_rate": 0,
        "surcharge_yen": 0,
        "additional_fee_yen": 0,
        "other_additional_fee_yen": 0,
    }
    services = [
        {
            **base,
            "service": "International Connect Plus (FICP)",
            "weight_basis": "greater",
            "volumetric_divisor_cm3_per_kg": 5000,
            "rounding_unit_g": 1,
            "max_weight_g": 68000,
            "max_actual_weight_g": 68000,
            "max_size": {"length_cm": 274, "length_plus_girth_cm": 330},
            "rates": ficp_rates,
        },
        {
            **base,
            "service": "International Priority Envelope",
            "weight_basis": "actual",
            "rounding_unit_g": 1,
            "max_weight_g": 500,
            "max_actual_weight_g": 500,
            "max_size": {"length_cm": 33.5, "width_cm": 23.5},
            "rates": build_zone_rates(group1, ip_env_1) + build_zone_rates(group2, ip_env_2),
        },
        {
            **base,
            "service": "International Priority Pak",
            "weight_basis": "actual",
            "rounding_unit_g": 1,
            "max_weight_g": 2500,
            "max_actual_weight_g": 2500,
            "max_size": {"length_cm": 52.71, "width_cm": 44.45, "volume_cm3": 15400},
            "rates": build_zone_rates(group1, ip_pak_1) + build_zone_rates(group2, ip_pak_2),
        },
        {
            **base,
            "service": "International Priority Package",
            "weight_basis": "greater",
            "volumetric_divisor_cm3_per_kg": 5000,
            "rounding_unit_g": 1,
            "max_weight_g": 68000,
            "max_actual_weight_g": 68000,
            "max_size": {"length_cm": 274, "length_plus_girth_cm": 330},
            "rates": build_zone_rates(group1, ip_pkg_1) + build_zone_rates(group2, ip_pkg_2),
        },
    ]
    metadata = {
        "rate_rows_ficp": len(ficp_rows_group1 + ficp_rows_group2),
        "rate_rows_ip_envelope": len(ip_env_1 + ip_env_2),
        "rate_rows_ip_pak": len(ip_pak_1 + ip_pak_2),
        "rate_rows_ip_package": len(ip_pkg_1 + ip_pkg_2),
        "zones": len(group1 + group2),
        "countries_from_zone_table": count_country_codes(PDF_PATHS["fedex"], 12),
        "rate_count": sum(len(service["rates"]) for service in services),
    }
    return services, metadata


def count_country_codes(pdf_path: Path, page_number: int) -> int:
    with pdfplumber.open(pdf_path) as pdf:
        text = pdf.pages[page_number - 1].extract_text(x_tolerance=1, y_tolerance=3) or ""
    codes = set(re.findall(r"\b[A-Z]{2}\b", text))
    codes -= {"PO", "DD", "KG", "JP", "IS"}
    return len(codes)


def main() -> None:
    missing = [str(path) for path in PDF_PATHS.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("PDFが見つかりません: " + ", ".join(missing))

    japan_post_services, japan_post_metadata = build_japan_post_services()
    orange_services, orange_metadata = build_orange_services()
    unregistered_services, unregistered_metadata = build_unregistered_services()
    dhl_services, dhl_metadata = build_dhl_services()
    fedex_services, fedex_metadata = build_fedex_services()
    services = japan_post_services + orange_services + unregistered_services + dhl_services + fedex_services

    data = {
        "version": "official-pdf-extract-2026-07-30",
        "currency": "JPY",
        "note": "PDF料金ガイドから抽出した公式料金データ。燃油サーチャージなど外部URL参照の変動費は0円として扱い、必要時はJSON側で更新してください。",
        "source_pdfs": {key: str(path) for key, path in PDF_PATHS.items()},
        "ui_countries": list(DEFAULT_DESTINATION_COUNTRY_CODES),
        "metadata": {
            "japan_post": japan_post_metadata,
            "orange": orange_metadata,
            "unregistered": unregistered_metadata,
            "dhl": dhl_metadata,
            "fedex": fedex_metadata,
            "services": len(services),
            "rate_count": sum(len(service.get("rates", [])) for service in services),
        },
        "services": services,
    }
    OUTPUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(data["metadata"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
