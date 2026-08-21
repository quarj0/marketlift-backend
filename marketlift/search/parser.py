from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

from .contracts import ParsedMarketplaceQuery
from .normalization import extract_unit_tokens_and_clean, normalize_text, strip_accents

# Intentionally small. These are grammar words, not marketplace concepts.
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
}

_MONEY = r"(?:r\$\s*)?(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
_RANGE_PATTERNS = [
    re.compile(rf"\bbetween\s+{_MONEY}\s+(?:and|to)\s+{_MONEY}\b", re.I),
    re.compile(rf"\bentre\s+{_MONEY}\s+e\s+{_MONEY}\b", re.I),
    re.compile(rf"\bde\s+{_MONEY}\s+a\s+{_MONEY}\b", re.I),
]
_MAX_PATTERNS = [
    re.compile(
        rf"\b(?:under|below|less\s+than|up\s+to|max(?:imum)?|ate|abaixo\s+de|menos\s+de|maximo(?:\s+de)?)\s+{_MONEY}\b",
        re.I,
    ),
    re.compile(rf"(?:<=|≤)\s*{_MONEY}", re.I),
    re.compile(rf"{_MONEY}\s+(?:or\s+less|ou\s+menos)\b", re.I),
]
_MIN_PATTERNS = [
    re.compile(
        rf"\b(?:over|above|more\s+than|at\s+least|min(?:imum)?|acima\s+de|mais\s+de|a\s+partir\s+de|minimo(?:\s+de)?)\s+{_MONEY}\b",
        re.I,
    ),
    re.compile(rf"(?:>=|≥)\s*{_MONEY}", re.I),
    re.compile(rf"{_MONEY}\s+(?:or\s+more|ou\s+mais)\b", re.I),
]


def _money_decimal(raw: str) -> Decimal:
    value = raw.strip().replace(" ", "")
    if "," in value and "." in value:
        value = value.replace(".", "").replace(",", ".")
    elif "," in value:
        value = value.replace(".", "").replace(",", ".")
    elif value.count(".") == 1:
        before, after = value.split(".")
        # In BRL searches, 1.200 is overwhelmingly a thousands separator.
        if len(after) == 3 and len(before) <= 3:
            value = before + after
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError({"q": "Invalid price in search query."}) from exc
    if number < 0:
        raise ValidationError({"q": "Search prices cannot be negative."})
    return number


def _remove_span(text: str, start: int, end: int) -> str:
    return text[:start] + (" " * (end - start)) + text[end:]


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

    remaining, min_price, max_price = _extract_prices(raw)
    remaining, spec_tokens = extract_unit_tokens_and_clean(remaining)
    normalized = normalize_text(remaining)

    core: list[str] = []
    for token in normalized.split():
        if token in STOP_WORDS or token in spec_tokens:
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
    )
