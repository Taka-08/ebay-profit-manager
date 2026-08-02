from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DestinationCountry:
    code: str
    english_name: str
    japanese_name: str
    aliases: tuple[str, ...] = ()


EU27_COUNTRY_CODES = (
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
    "SK",
    "SI",
    "SE",
    "DE",
)


COUNTRIES = (
    DestinationCountry("US", "United States", "アメリカ", ("USA", "America", "米国", "アメリカ合衆国")),
    DestinationCountry("CA", "Canada", "カナダ"),
    DestinationCountry("GB", "United Kingdom", "イギリス", ("UK", "Great Britain", "英国")),
    DestinationCountry("AU", "Australia", "オーストラリア", ("豪州",)),
    DestinationCountry("AT", "Austria", "オーストリア"),
    DestinationCountry("BE", "Belgium", "ベルギー"),
    DestinationCountry("BG", "Bulgaria", "ブルガリア"),
    DestinationCountry("CY", "Cyprus", "キプロス"),
    DestinationCountry("CZ", "Czechia", "チェコ", ("Czech Republic",)),
    DestinationCountry("DK", "Denmark", "デンマーク"),
    DestinationCountry("EE", "Estonia", "エストニア"),
    DestinationCountry("ES", "Spain", "スペイン"),
    DestinationCountry("FI", "Finland", "フィンランド"),
    DestinationCountry("FR", "France", "フランス"),
    DestinationCountry("GR", "Greece", "ギリシャ"),
    DestinationCountry("HR", "Croatia", "クロアチア"),
    DestinationCountry("HU", "Hungary", "ハンガリー"),
    DestinationCountry("IE", "Ireland", "アイルランド"),
    DestinationCountry("IT", "Italy", "イタリア"),
    DestinationCountry("LT", "Lithuania", "リトアニア"),
    DestinationCountry("LU", "Luxembourg", "ルクセンブルク"),
    DestinationCountry("LV", "Latvia", "ラトビア"),
    DestinationCountry("MT", "Malta", "マルタ"),
    DestinationCountry("NL", "Netherlands", "オランダ", ("The Netherlands",)),
    DestinationCountry("PL", "Poland", "ポーランド"),
    DestinationCountry("PT", "Portugal", "ポルトガル"),
    DestinationCountry("RO", "Romania", "ルーマニア"),
    DestinationCountry("SK", "Slovakia", "スロバキア"),
    DestinationCountry("SI", "Slovenia", "スロベニア"),
    DestinationCountry("SE", "Sweden", "スウェーデン"),
    DestinationCountry("DE", "Germany", "ドイツ"),
)


COUNTRY_BY_CODE = {country.code: country for country in COUNTRIES}
_ALIASES: dict[str, str] = {}
for _country in COUNTRIES:
    for _alias in (
        _country.code,
        _country.english_name,
        _country.japanese_name,
        *_country.aliases,
    ):
        _ALIASES[_alias.strip().casefold()] = _country.code


DEFAULT_DESTINATION_COUNTRY_CODES = (
    "US",
    "CA",
    "GB",
    "AU",
    *EU27_COUNTRY_CODES,
)


def normalize_destination_country(value: object) -> str:
    """Return the ISO 3166-1 alpha-2 code for supported country aliases."""
    text = str(value or "").strip()
    if not text:
        return ""
    return _ALIASES.get(text.casefold(), text.upper() if len(text) == 2 else text)


def destination_country_label(value: object, *, include_code: bool = True) -> str:
    code = normalize_destination_country(value)
    country = COUNTRY_BY_CODE.get(code)
    if country is None:
        return str(value or "")
    if include_code:
        return f"{country.japanese_name} ({country.code})"
    return country.japanese_name


def destination_country_english_name(value: object) -> str:
    code = normalize_destination_country(value)
    country = COUNTRY_BY_CODE.get(code)
    return country.english_name if country else str(value or "")
