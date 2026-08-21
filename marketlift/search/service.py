from __future__ import annotations

import importlib
import re
import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError

from categories.models import CategoryField
from listings.models import Listing
from sellers.models import SellerProfile

from .contracts import SearchPage, SearchRequest
from .parser import parse_marketplace_query
from .regions import BRAZIL_REGION_STATES, BRAZIL_STATE_CODES
from marketlift.location.validators import (
    normalize_country_code,
    validate_coordinates,
    validate_radius_km,
)

_ATTR_KEY_RE = re.compile(r"^[a-z0-9_]{1,80}$")
ALLOWED_SORTS = {"relevant", "newest", "price_asc", "price_desc", "distance"}
ALLOWED_DATE_FILTERS = {None, "", "today", "week", "month"}


def _load_backend():
    dotted = getattr(
        settings,
        "MARKETLIFT_SEARCH_BACKEND",
        "marketlift.search.backends.postgres.PostgresListingSearchBackend",
    )
    module_name, class_name = dotted.rsplit(".", 1)
    return getattr(importlib.import_module(module_name), class_name)()


def _validate_decimal(name: str, value: Decimal | None) -> None:
    if value is None:
        return
    if value < 0:
        raise ValidationError({name: "Price cannot be negative."})
    if value > Decimal("999999999999.99"):
        raise ValidationError({name: "Price exceeds the supported search range."})


def _validate_attribute_filters(filters: dict, *, category: str | None) -> dict:
    if not isinstance(filters, dict):
        raise ValidationError({"attributes": "Attribute filters must be an object."})
    if len(filters) > 20:
        raise ValidationError(
            {"attributes": "At most 20 attribute filters are allowed."}
        )
    if not filters:
        return {}

    keys = list(filters)
    for key in keys:
        if not isinstance(key, str) or not _ATTR_KEY_RE.fullmatch(key):
            raise ValidationError({"attributes": "Invalid attribute filter key."})

    allowed = CategoryField.objects.filter(filterable=True, category__active=True)
    if category:
        allowed = allowed.filter(category__slug=category)
    field_types_by_key: dict[str, set[str]] = {}
    for key, field_type in allowed.filter(key__in=keys).values_list(
        "key", "field_type"
    ):
        field_types_by_key.setdefault(key, set()).add(field_type)

    unknown = sorted(set(keys) - set(field_types_by_key))
    if unknown:
        raise ValidationError(
            {"attributes": f"Unsupported filter fields: {', '.join(unknown)}."}
        )

    cleaned: dict = {}
    for key, value in filters.items():
        types = field_types_by_key[key]
        storage_kinds = {
            (
                "number"
                if field_type == CategoryField.FieldType.NUMBER
                else (
                    "boolean"
                    if field_type == CategoryField.FieldType.BOOLEAN
                    else "text"
                )
            )
            for field_type in types
        }
        if len(storage_kinds) != 1:
            raise ValidationError(
                {"attributes": f"Filter field {key} is ambiguous without a category."}
            )
        storage_kind = next(iter(storage_kinds))

        if isinstance(value, dict):
            if storage_kind != "number":
                raise ValidationError(
                    {
                        "attributes": f"Range filtering is only valid for numeric field {key}."
                    }
                )
            unexpected = set(value) - {"min", "max"}
            if unexpected:
                raise ValidationError({"attributes": f"Invalid range for {key}."})
            cleaned_range = {}
            for side in ("min", "max"):
                raw = value.get(side)
                if raw in (None, ""):
                    continue
                try:
                    cleaned_range[side] = Decimal(str(raw))
                except (InvalidOperation, TypeError, ValueError) as exc:
                    raise ValidationError(
                        {"attributes": f"{key}.{side} must be numeric."}
                    ) from exc
            if (
                "min" in cleaned_range
                and "max" in cleaned_range
                and cleaned_range["min"] > cleaned_range["max"]
            ):
                raise ValidationError({"attributes": f"{key} range is reversed."})
            cleaned[key] = cleaned_range
            continue

        if value in (None, ""):
            continue
        if storage_kind == "number":
            try:
                cleaned[key] = Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ValidationError(
                    {"attributes": f"{key} must be numeric."}
                ) from exc
        elif storage_kind == "boolean":
            if isinstance(value, bool):
                cleaned[key] = value
            else:
                lowered = str(value).strip().casefold()
                if lowered not in {"true", "false", "1", "0"}:
                    raise ValidationError(
                        {"attributes": f"{key} must be true or false."}
                    )
                cleaned[key] = lowered in {"true", "1"}
        else:
            text = str(value).strip()
            if len(text) > 120:
                raise ValidationError({"attributes": f"{key} filter is too long."})
            cleaned[key] = text
    return cleaned


def validate_search_request(request: SearchRequest) -> SearchRequest:
    limits = {
        "category": 80,
        "country_code": 2,
        "region": 8,
        "state": 8,
        "city": 100,
        "district": 120,
        "condition": 24,
        "seller_type": 24,
        "seller_id": 64,
    }
    for field, limit in limits.items():
        value = getattr(request, field)
        if value is not None and len(str(value)) > limit:
            raise ValidationError({field: f"Value cannot exceed {limit} characters."})

    region = (request.region or "").strip().upper() or None
    state = (request.state or "").strip().upper() or None
    country_code = (
        normalize_country_code(request.country_code) if request.country_code else "BR"
    )
    if country_code != "BR":
        raise ValidationError(
            {"country_code": "Marketlift currently supports Brazil only."}
        )
    if region and region not in BRAZIL_REGION_STATES:
        raise ValidationError({"region": "Unsupported Brazilian region."})
    if state and state not in BRAZIL_STATE_CODES:
        raise ValidationError({"state": "Unsupported Brazilian state."})
    if region and state and state not in BRAZIL_REGION_STATES[region]:
        raise ValidationError(
            {"state": "Selected state does not belong to the selected region."}
        )

    lat, lng = validate_coordinates(request.latitude, request.longitude)
    radius = validate_radius_km(request.radius_km)
    if radius is not None and lat is None:
        raise ValidationError(
            {"radius_km": "Radius search requires latitude and longitude."}
        )
    if request.sort == "distance" and lat is None:
        raise ValidationError(
            {"sort": "Distance sorting requires latitude and longitude."}
        )

    if request.sort not in ALLOWED_SORTS:
        raise ValidationError({"sort": "Unsupported search sort."})
    if request.date_listed not in ALLOWED_DATE_FILTERS:
        raise ValidationError({"date_listed": "Unsupported date filter."})

    condition = request.condition
    if condition:
        condition_map = {
            str(value).casefold(): str(value) for value, _ in Listing.Condition.choices
        }
        canonical_condition = condition_map.get(str(condition).strip().casefold())
        if canonical_condition is None:
            raise ValidationError({"condition": "Unsupported listing condition."})
    else:
        canonical_condition = None

    seller_type = request.seller_type
    if seller_type:
        seller_type_map = {
            str(value).casefold(): str(value)
            for value, _ in SellerProfile.SellerType.choices
        }
        canonical_seller_type = seller_type_map.get(str(seller_type).strip().casefold())
        if canonical_seller_type is None:
            raise ValidationError({"seller_type": "Unsupported seller type."})
    else:
        canonical_seller_type = None

    if request.seller_id:
        try:
            uuid.UUID(str(request.seller_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValidationError({"seller_id": "Invalid seller ID."}) from exc
    if request.page_size < 1:
        raise ValidationError({"page_size": "Page size must be positive."})
    max_page_size = getattr(settings, "MARKETLIFT_SEARCH_MAX_PAGE_SIZE", 50)
    if request.page_size > max_page_size:
        raise ValidationError(
            {"page_size": f"Page size cannot exceed {max_page_size}."}
        )
    _validate_decimal("min_price", request.min_price)
    _validate_decimal("max_price", request.max_price)
    if (
        request.min_price is not None
        and request.max_price is not None
        and request.min_price > request.max_price
    ):
        raise ValidationError({"price": "Minimum price cannot exceed maximum price."})

    attrs = _validate_attribute_filters(
        request.attribute_filters or {}, category=request.category
    )
    return SearchRequest(
        **{
            **request.__dict__,
            "country_code": country_code,
            "region": region,
            "state": state,
            "latitude": lat,
            "longitude": lng,
            "radius_km": radius,
            "condition": canonical_condition,
            "seller_type": canonical_seller_type,
            "attribute_filters": attrs,
        }
    )


def search_listings(request: SearchRequest) -> SearchPage:
    request = validate_search_request(request)
    parsed = parse_marketplace_query(
        request.q,
        max_length=getattr(settings, "MARKETLIFT_SEARCH_MAX_QUERY_LENGTH", 160),
    )
    # Parsed natural-language prices are untrusted input too, even when an
    # explicit UI price filter is also present. Validate both independently;
    # the backend then combines them using the stricter bound.
    _validate_decimal("min_price", parsed.min_price)
    _validate_decimal("max_price", parsed.max_price)
    return _load_backend().search(request, parsed)
