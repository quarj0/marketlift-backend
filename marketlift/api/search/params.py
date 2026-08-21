from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import ValidationError

from marketlift.search.contracts import SearchRequest

_ATTR_RE = re.compile(r"^attr\.([a-z0-9_]{1,80})(?:\.(min|max))?$")


def _decimal(name: str, raw: str | None) -> Decimal | None:
    if raw in (None, ""):
        return None
    value = str(raw).strip().replace(" ", "")
    # Query parameters are API values, not natural-language BRL syntax. Accept
    # either 800.50 or 800,50, but not thousands separators here.
    if "," in value and "." not in value:
        value = value.replace(",", ".")
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError({name: "Must be a valid number."}) from exc


def _bool(name: str, raw: str | None) -> bool:
    if raw in (None, "", "0", "false", "False", "no", "off"):
        return False
    if raw in ("1", "true", "True", "yes", "on"):
        return True
    raise ValidationError({name: "Must be true or false."})


def _int(name: str, raw: str | None, default: int) -> int:
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError({name: "Must be an integer."}) from exc


def _attribute_filters(params) -> dict:
    result: dict = {}
    for key in params.keys():
        match = _ATTR_RE.fullmatch(key)
        if not match:
            continue
        field, bound = match.groups()
        raw = params.get(key)
        if bound:
            current = result.setdefault(field, {})
            if not isinstance(current, dict):
                raise ValidationError({key: "Cannot combine exact and range filters."})
            current[bound] = raw
        else:
            if field in result and isinstance(result[field], dict):
                raise ValidationError({key: "Cannot combine exact and range filters."})
            lowered = str(raw).strip().casefold()
            if lowered in {"true", "false"}:
                result[field] = lowered == "true"
            else:
                result[field] = raw
    return result


def search_request_from_query_params(params) -> SearchRequest:
    if len(params) > 45:
        raise ValidationError({"query": "Too many search parameters."})

    return SearchRequest(
        q=(params.get("q") or "").strip(),
        category=(params.get("category") or "").strip() or None,
        region=(params.get("region") or "").strip().upper() or None,
        state=(params.get("state") or params.get("state_code") or "").strip() or None,
        city=(params.get("city") or "").strip() or None,
        district=(params.get("district") or "").strip() or None,
        min_price=_decimal(
            "min_price", params.get("min_price") or params.get("minPrice")
        ),
        max_price=_decimal(
            "max_price", params.get("max_price") or params.get("maxPrice")
        ),
        condition=(params.get("condition") or "").strip() or None,
        seller_type=(
            params.get("seller_type") or params.get("sellerType") or ""
        ).strip()
        or None,
        seller_id=(params.get("seller_id") or params.get("sellerId") or "").strip()
        or None,
        verified_only=_bool(
            "verified_only", params.get("verified_only") or params.get("verifiedOnly")
        ),
        date_listed=(
            params.get("date_listed") or params.get("dateListed") or ""
        ).strip()
        or None,
        attribute_filters=_attribute_filters(params),
        sort=(params.get("sort") or "relevant").strip(),
        page_size=_int(
            "page_size", params.get("page_size") or params.get("pageSize"), 24
        ),
        cursor=(params.get("cursor") or "").strip() or None,
    )
