from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

_SPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:\+[a-z0-9]*)?", re.IGNORECASE)
_UNIT_RE = re.compile(
    r"(?<![a-z0-9])(?P<number>\d+(?:[.,]\d+)?)\s*(?P<unit>gb|tb|mb|km|kg|m2|m²|cm|mm|in|inch|polegadas|%)\b",
    re.IGNORECASE,
)

UNIT_ALIASES = {
    "m²": "m2",
    "inch": "in",
    "polegadas": "in",
}


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_text(value: str) -> str:
    value = strip_accents(value).casefold()
    value = value.replace("_", " ")
    # Treat punctuation as token boundaries; keep a trailing + for model names such as S21+.
    value = re.sub(r"[^a-z0-9%+]+", " ", value)
    return _SPACE_RE.sub(" ", value).strip()


def compact_decimal(value: Decimal | int | float | str) -> str:
    number = Decimal(str(value))
    if number == number.to_integral():
        return str(number.quantize(Decimal("1")))
    return format(number.normalize(), "f")


def normalize_unit_token(number: str, unit: str) -> str:
    unit = UNIT_ALIASES.get(
        strip_accents(unit).casefold(), strip_accents(unit).casefold()
    )
    number = number.replace(",", ".")
    try:
        compact = compact_decimal(number)
    except Exception:
        compact = number
    return f"{compact}{unit}"


def extract_unit_tokens(value: str) -> list[str]:
    normalized = strip_accents(value or "").casefold()
    tokens: list[str] = []
    for match in _UNIT_RE.finditer(normalized):
        token = normalize_unit_token(match.group("number"), match.group("unit"))
        if token not in tokens:
            tokens.append(token)
    return tokens


def extract_unit_tokens_and_clean(value: str) -> tuple[str, list[str]]:
    normalized = strip_accents(value or "").casefold()
    tokens: list[str] = []
    pieces: list[str] = []
    last = 0
    for match in _UNIT_RE.finditer(normalized):
        pieces.append(normalized[last : match.start()])
        pieces.append(" " * (match.end() - match.start()))
        token = normalize_unit_token(match.group("number"), match.group("unit"))
        if token not in tokens:
            tokens.append(token)
        last = match.end()
    pieces.append(normalized[last:])
    return "".join(pieces), tokens


def tokenize(value: str) -> list[str]:
    normalized = normalize_text(value)
    tokens = [match.group(0) for match in _TOKEN_RE.finditer(normalized)]
    for token in list(tokens):
        if token.endswith("+") and len(token) > 1 and token[:-1] not in tokens:
            tokens.append(token[:-1])
    for compact in extract_unit_tokens(value):
        if compact not in tokens:
            tokens.append(compact)
    return tokens


def attribute_unit_tokens(value: object, unit: str | None) -> list[str]:
    if value in (None, "") or not unit:
        return []
    normalized_unit = UNIT_ALIASES.get(
        strip_accents(str(unit)).casefold(), strip_accents(str(unit)).casefold()
    )
    # Compound units such as R$/month are not product-spec tokens.
    if normalized_unit not in {
        "gb",
        "tb",
        "mb",
        "km",
        "kg",
        "m2",
        "cm",
        "mm",
        "in",
        "%",
    }:
        return []
    try:
        compact = compact_decimal(value)
    except Exception:
        compact = normalize_text(str(value)).replace(" ", "")
    if not compact:
        return []
    result = [f"{compact}{normalized_unit}"]
    # Give common storage capacities a TB alias without changing the stored value.
    if normalized_unit == "gb":
        try:
            gb = Decimal(compact)
            if gb >= 1024 and gb % 1024 == 0:
                result.append(f"{compact_decimal(gb / 1024)}tb")
        except Exception:
            pass
    return result
