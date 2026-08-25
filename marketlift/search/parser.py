from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

from .contracts import NumericSpecificationConstraint, ParsedMarketplaceQuery
from .normalization import (
    extract_unit_tokens_and_clean,
    normalize_text,
    normalize_unit_token,
    strip_accents,
)

# Grammar and common attribute-label words that should not become hard search
# requirements. Marketplace concepts such as brand/model names are intentionally
# not included here.
STOP_WORDS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "the",
    "to",
    "with",
    "near",
    "per",
    "month",
    "de",
    "da",
    "das",
    "do",
    "dos",
    "e",
    "em",
    "na",
    "nas",
    "no",
    "nos",
    "para",
    "por",
    "mes",
    "com",
    "um",
    "uma",
    "uns",
    "umas",
    "partir",
    "ate",
    "abaixo",
    "acima",
    "menos",
    "mais",
    "pelo",
    "minimo",
    "maximo",
    # French marketplace grammar
    "avec",
    "dans",
    "du",
    "des",
    "et",
    "moins",
    "plus",
    "jusqu",
    "au",
}

# When an explicit unit is present, these words describe the specification
# rather than the product. Removing them prevents queries such as
# ``16 GB de memória`` from requiring the literal Portuguese label ``memoria``
# to exist in an otherwise correctly structured listing document.
_SPEC_LABEL_WORDS = {
    "ram",
    "memory",
    "memoria",
    "storage",
    "armazenamento",
    "capacity",
    "capacidade",
    "screen",
    "tela",
    "area",
    "peso",
    "mileage",
    "quilometragem",
    "rodados",
}

# Currency-aware marketplace amounts. The parser accepts Brazilian and common
# African notation but emits one neutral Decimal range for the search backend.
# Examples: R$9.000, GH₵6,000, ₦1.5m, KSh 1.8m, R 25 000, FCFA 500000.
_NUMBER = r"(?:\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
_SCALE = r"(?:\s*(?:k|m|mil|milhao|milhoes|thousand|million|millions))?"
_PREFIX = r"(?:(?:r\$|brl|gh₵|ghs|₵|ngn|₦|ksh|kes|zar|xof|fcfa|cfa|r(?!\$))\s*)?"
_SUFFIX = r"(?:\s*(?:real|reais|brl|cedi|cedis|ghs|naira|ngn|shilling|shillings|kes|rand|zar|xof|fcfa|cfa))?"
_PRODUCT_UNIT = r"(?:gb|gigabytes?|gigas?|giga|tb|terabytes?|teras?|tera|mb|megabytes?|megas?|mega|km|kg|m2|m²|cm|mm|inch|polegada|polegadas|l|litro|litros|%)"
_MONEY = rf"({_PREFIX}{_NUMBER}{_SCALE}{_SUFFIX})(?![a-z0-9.,])(?!\s*(?:k|m|mil|milhao|milhoes|thousand|million|millions)\b)(?!\s*{_PRODUCT_UNIT}(?![a-z0-9]))"

_RANGE_PATTERNS = [
    re.compile(rf"\bbetween\s+{_MONEY}\s+(?:and|to)\s+{_MONEY}\b", re.I),
    re.compile(rf"\bentre\s+{_MONEY}\s+e\s+{_MONEY}\b", re.I),
    re.compile(rf"\bentre\s+{_MONEY}\s+et\s+{_MONEY}\b", re.I),
    re.compile(rf"\bde\s+{_MONEY}\s+a\s+{_MONEY}\b", re.I),
]
_MAX_PATTERNS = [
    re.compile(
        rf"\b(?:under|below|less\s+than|up\s+to|max(?:imum)?|ate|abaixo\s+de|menos\s+de|maximo(?:\s+de)?|no\s+maximo(?:\s+de)?|moins\s+de|jusqu(?:a|\s+a))\s+{_MONEY}\b",
        re.I,
    ),
    re.compile(rf"(?:<=|≤)\s*{_MONEY}", re.I),
    re.compile(rf"{_MONEY}\s+(?:or\s+less|ou\s+menos)\b", re.I),
]
_MIN_PATTERNS = [
    re.compile(
        rf"\b(?:over|above|more\s+than|at\s+least|min(?:imum)?|acima\s+de|mais\s+de|pelo\s+menos|minimo(?:\s+de)?|no\s+minimo(?:\s+de)?|plus\s+de|au\s+moins)\s+{_MONEY}\b",
        re.I,
    ),
    re.compile(rf"(?:>=|≥)\s*{_MONEY}", re.I),
    re.compile(rf"{_MONEY}\s+(?:or\s+more|ou\s+mais)\b", re.I),
]
_STARTING_FROM_PATTERN = re.compile(rf"\ba\s+partir\s+de\s+{_MONEY}\b", re.I)

_RADIUS_PATTERNS = [
    re.compile(r"\bwithin\s+(\d+(?:[.,]\d+)?)\s*km\s+(?:of|from)\s+me\b", re.I),
    re.compile(
        r"\b(?:ate|a)\s+(\d+(?:[.,]\d+)?)\s*km\s+(?:de\s+mim|daqui)\b",
        re.I,
    ),
    re.compile(r"\b(\d+(?:[.,]\d+)?)\s*km\s+(?:de\s+mim|from\s+me)\b", re.I),
    re.compile(
        r"\b(?:em\s+um\s+raio\s+de|num\s+raio\s+de|raio\s+de)\s+(\d+(?:[.,]\d+)?)\s*km\b",
        re.I,
    ),
]
_YEAR = r"(?P<year>(?:19|20)\d{2}|2100)(?!\s*(?:reais?|brl|k|mil|milhao|milhoes)\b)"
_YEAR_MIN_INCLUSIVE_PATTERNS = [
    re.compile(rf"\ba\s+partir\s+de\s+{_YEAR}\b", re.I),
    re.compile(
        rf"\b{_YEAR}\s+(?:ou\s+mais\s+novo|ou\s+mais\s+recente|or\s+newer)\b", re.I
    ),
    re.compile(rf"\b(?:ano|year)\s*(?:>=|a\s+partir\s+de|from)\s*{_YEAR}\b", re.I),
]
_YEAR_MIN_EXCLUSIVE_PATTERNS = [
    re.compile(rf"\b(?:after|depois\s+de)\s+{_YEAR}\b", re.I),
    re.compile(rf"\b(?:ano|year)\s+(?:acima\s+de|above)\s+{_YEAR}\b", re.I),
]
_YEAR_MAX_INCLUSIVE_PATTERNS = [
    re.compile(rf"\b(?:ano|year)\s*(?:<=|ate|up\s+to)\s*{_YEAR}\b", re.I),
    re.compile(rf"\b{_YEAR}\s+(?:ou\s+mais\s+antigo|or\s+older)\b", re.I),
]
_YEAR_MAX_EXCLUSIVE_PATTERNS = [
    re.compile(rf"\b(?:before|antes\s+de)\s+{_YEAR}\b", re.I),
    re.compile(rf"\b(?:ano|year)\s+(?:abaixo\s+de|below)\s+{_YEAR}\b", re.I),
]

_SPEC_RANGE_UNIT = r"(?:gb|gigabytes?|gigas?|giga|tb|terabytes?|teras?|tera|mb|megabytes?|megas?|mega|km|kg|m2|m²|cm|mm|in|inch|polegada|polegadas|l|litro|litros|%)"
_SPEC_RANGE_QUANTITY = (
    rf"(?P<number>{_NUMBER})\s*(?P<scale>k|mil)?\s*(?P<unit>{_SPEC_RANGE_UNIT})"
)
_SPEC_RANGE_LABEL = r"(?:\s+(?:de\s+)?(?P<label>ram|memoria(?:\s+ram)?|memory|storage|armazenamento|capacidade|mileage|quilometragem|rodados|screen|tela|battery|bateria|area))?"
_SPEC_MAX_PATTERN = re.compile(
    rf"\b(?:under|below|less\s+than|up\s+to|max(?:imum)?|ate|abaixo\s+de|menos\s+de|maximo(?:\s+de)?|no\s+maximo(?:\s+de)?|moins\s+de|jusqu(?:a|\s+a))\s+{_SPEC_RANGE_QUANTITY}{_SPEC_RANGE_LABEL}(?![a-z0-9])",
    re.I,
)
_SPEC_MIN_PATTERN = re.compile(
    rf"\b(?:over|above|more\s+than|at\s+least|min(?:imum)?|acima\s+de|mais\s+de|pelo\s+menos|minimo(?:\s+de)?|no\s+minimo(?:\s+de)?|a\s+partir\s+de)\s+{_SPEC_RANGE_QUANTITY}{_SPEC_RANGE_LABEL}(?![a-z0-9])",
    re.I,
)

_NEAR_ME_PATTERNS = [
    re.compile(r"\bnear\s+me\b", re.I),
    re.compile(r"\bclose\s+to\s+me\b", re.I),
    re.compile(r"\baround\s+me\b", re.I),
    re.compile(r"\bperto\s+de\s+mim\b", re.I),
    re.compile(r"\bproximo\s+(?:de|a)\s+mim\b", re.I),
]


def _money_decimal(raw: str) -> Decimal:
    value = strip_accents(raw or "").strip().casefold()
    value = re.sub(r"\s+", "", value)
    value = re.sub(
        r"^(?:r\$|brl|gh₵|ghs|₵|ngn|₦|ksh|kes|zar|xof|fcfa|cfa|r(?=\d))",
        "",
        value,
    )
    value = re.sub(
        r"(?:reais?|brl|cedis?|ghs|naira|ngn|shillings?|kes|rand|zar|xof|fcfa|cfa)$",
        "",
        value,
    )

    multiplier = Decimal("1")
    scale_match = re.search(
        r"(millions|million|milhoes|milhao|thousand|mil|m|k)$", value
    )
    if scale_match:
        scale = scale_match.group(1)
        value = value[: scale_match.start()]
        if scale in {"million", "millions", "milhao", "milhoes", "m"}:
            multiplier = Decimal("1000000")
        else:
            multiplier = Decimal("1000")

    # Infer the decimal separator from the last separator when both are present.
    # With one separator, three trailing digits are treated as a thousands group
    # unless a magnitude suffix (1.5m / 1,5 mil) makes it clearly decimal.
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        before, after = value.rsplit(",", 1)
        if len(after) == 3 and multiplier == 1:
            value = before.replace(",", "") + after
        else:
            value = value.replace(",", ".")
    elif value.count(".") >= 1:
        parts = value.split(".")
        if len(parts) > 2 and all(len(part) == 3 for part in parts[1:]):
            value = "".join(parts)
        elif len(parts) == 2:
            before, after = parts
            if len(after) == 3 and multiplier == 1 and len(before) <= 3:
                value = before + after

    try:
        number = Decimal(value) * multiplier
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError({"q": "Invalid price in search query."}) from exc
    if number < 0:
        raise ValidationError({"q": "Search prices cannot be negative."})
    return number


def _looks_like_unqualified_year(raw: str) -> bool:
    """Guard ambiguous ``a partir de 2020`` from becoming a R$2,020 price.

    Currency markers and magnitude words make the intent monetary. A bare
    four-digit value in the normal vehicle/model-year range is kept as a text
    token so category attributes can match it instead.
    """
    normalized = strip_accents(raw or "").casefold().strip()
    if re.search(
        r"r\$|\b(?:brl|ghs|ngn|kes|zar|xof|fcfa|cfa|reais?|cedis?|naira|rand|shillings?)\b|[₦₵]|\b(?:k|m|mil|milhao|milhoes|thousand|million|millions)\b",
        normalized,
    ):
        return False
    try:
        number = _money_decimal(normalized)
    except ValidationError:
        return False
    return number == number.to_integral() and Decimal("1900") <= number <= Decimal(
        "2100"
    )


def _remove_span(text: str, start: int, end: int) -> str:
    return text[:start] + (" " * (end - start)) + text[end:]


def _spec_constraint_key(unit: str, label: str | None) -> str | None:
    normalized_label = normalize_text(label or "")
    if unit == "gb":
        if normalized_label in {"ram", "memory", "memoria", "memoria ram"}:
            return "ram_gb"
        if normalized_label in {"storage", "armazenamento", "capacidade"}:
            return "storage_gb"
        return None
    if unit == "km":
        return "mileage_km"
    if unit == "in":
        return "screen_size"
    if unit == "%":
        return "battery_health"
    return None


def _spec_quantity(number: str, scale: str | None, unit: str) -> tuple[Decimal, str]:
    token = normalize_unit_token(number, unit, scale)
    match = re.fullmatch(r"(?P<number>[0-9]+(?:\.[0-9]+)?)(?P<unit>[a-z0-9%]+)", token)
    if not match:
        raise ValidationError({"q": "Invalid specification range in search query."})
    return Decimal(match.group("number")), match.group("unit")


def _extract_year_ranges(
    value: str,
) -> tuple[str, tuple[NumericSpecificationConstraint, ...]]:
    working = strip_accents(value or "").casefold()
    constraints: list[NumericSpecificationConstraint] = []
    groups = (
        ("min_inclusive", _YEAR_MIN_INCLUSIVE_PATTERNS),
        ("min_exclusive", _YEAR_MIN_EXCLUSIVE_PATTERNS),
        ("max_inclusive", _YEAR_MAX_INCLUSIVE_PATTERNS),
        ("max_exclusive", _YEAR_MAX_EXCLUSIVE_PATTERNS),
    )
    for _ in range(2):
        candidates = []
        for kind, patterns in groups:
            for pattern in patterns:
                match = pattern.search(working)
                if match:
                    candidates.append((match.start(), kind, match))
        if not candidates:
            break
        _, kind, match = min(candidates, key=lambda item: item[0])
        year = Decimal(match.group("year"))
        minimum = None
        maximum = None
        if kind == "min_inclusive":
            minimum = year
        elif kind == "min_exclusive":
            minimum = year + 1
        elif kind == "max_inclusive":
            maximum = year
        else:
            maximum = year - 1
        constraints.append(
            NumericSpecificationConstraint(key="year", minimum=minimum, maximum=maximum)
        )
        working = _remove_span(working, *match.span())
    return working, tuple(constraints)


def _extract_specification_ranges(
    value: str,
) -> tuple[str, tuple[NumericSpecificationConstraint, ...]]:
    working = strip_accents(value or "").casefold()
    constraints: list[NumericSpecificationConstraint] = []

    # Extract at most six explicit numeric range constraints. Always consume the
    # earliest one so mixed queries preserve their original semantics.
    for _ in range(6):
        candidates = []
        for kind, pattern in (("max", _SPEC_MAX_PATTERN), ("min", _SPEC_MIN_PATTERN)):
            match = pattern.search(working)
            if match:
                candidates.append((match.start(), kind, match))
        if not candidates:
            break
        _, kind, match = min(candidates, key=lambda item: item[0])
        number, unit = _spec_quantity(
            match.group("number"), match.group("scale"), match.group("unit")
        )
        key = _spec_constraint_key(unit, match.groupdict().get("label"))
        constraints.append(
            NumericSpecificationConstraint(
                unit=unit,
                minimum=number if kind == "min" else None,
                maximum=number if kind == "max" else None,
                key=key,
            )
        )
        working = _remove_span(working, *match.span())

    return working, tuple(constraints)


def _extract_radius(value: str) -> tuple[str, Decimal | None, bool]:
    working = strip_accents(value or "").casefold()
    radius: Decimal | None = None
    near_me = False

    for pattern in _RADIUS_PATTERNS:
        match = pattern.search(working)
        if match:
            try:
                radius = Decimal(match.group(1).replace(",", "."))
            except (InvalidOperation, ValueError) as exc:
                raise ValidationError({"q": "Invalid radius in search query."}) from exc
            if radius <= 0:
                raise ValidationError({"q": "Search radius must be positive."})
            near_me = True
            working = _remove_span(working, *match.span())
            break

    for pattern in _NEAR_ME_PATTERNS:
        match = pattern.search(working)
        if match:
            near_me = True
            working = _remove_span(working, *match.span())

    return working, radius, near_me


def _extract_prices(value: str) -> tuple[str, Decimal | None, Decimal | None]:
    working = strip_accents(value or "").casefold()
    min_price: Decimal | None = None
    max_price: Decimal | None = None

    for pattern in _RANGE_PATTERNS:
        match = pattern.search(working)
        if match:
            min_price = _money_decimal(match.group(1))
            max_price = _money_decimal(match.group(2))
            if min_price > max_price:
                raise ValidationError({"q": "Search price range is reversed."})
            working = _remove_span(working, *match.span())
            break

    for pattern in _MAX_PATTERNS:
        match = pattern.search(working)
        if match:
            max_price = _money_decimal(match.group(1))
            working = _remove_span(working, *match.span())
            break

    for pattern in _MIN_PATTERNS:
        match = pattern.search(working)
        if match:
            min_price = _money_decimal(match.group(1))
            working = _remove_span(working, *match.span())
            break

    if min_price is None:
        match = _STARTING_FROM_PATTERN.search(working)
        if match and not _looks_like_unqualified_year(match.group(1)):
            min_price = _money_decimal(match.group(1))
            working = _remove_span(working, *match.span())

    if min_price is not None and max_price is not None and min_price > max_price:
        raise ValidationError(
            {"q": "Search minimum price cannot exceed maximum price."}
        )
    return working, min_price, max_price


def parse_marketplace_query(
    value: str, *, max_length: int = 160
) -> ParsedMarketplaceQuery:
    raw = (value or "").strip()
    if len(raw) > max_length:
        raise ValidationError(
            {"q": f"Search query cannot exceed {max_length} characters."}
        )
    if any(ord(char) < 32 and char not in "\t\n\r" for char in raw):
        raise ValidationError(
            {"q": "Search query contains invalid control characters."}
        )

    remaining, radius_km, near_me = _extract_radius(raw)
    remaining, year_specifications = _extract_year_ranges(remaining)
    remaining, numeric_specifications = _extract_specification_ranges(remaining)
    numeric_specifications = year_specifications + numeric_specifications
    remaining, min_price, max_price = _extract_prices(remaining)
    remaining, spec_tokens = extract_unit_tokens_and_clean(remaining)
    normalized = normalize_text(remaining)

    core: list[str] = []
    for token in normalized.split():
        if token in STOP_WORDS or token in spec_tokens:
            continue
        if spec_tokens and token in _SPEC_LABEL_WORDS:
            continue
        if len(token) > 40:
            continue
        if token not in core:
            core.append(token)
        if len(core) >= 10:
            break

    # Keep only a handful of explicit unit specs to bound DB query complexity.
    spec_tokens = spec_tokens[:6]
    return ParsedMarketplaceQuery(
        original=raw,
        normalized=normalize_text(raw),
        core_tokens=tuple(core),
        specification_tokens=tuple(spec_tokens),
        min_price=min_price,
        max_price=max_price,
        radius_km=radius_km,
        near_me=near_me,
        numeric_specifications=numeric_specifications,
    )
