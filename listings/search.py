from __future__ import annotations
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.db import connection
from django.db.models import Exists, OuterRef, Q, Value
from django.utils import timezone
from marketlift.location.validators import validate_coordinates, validate_radius_km
from marketlift.locations import BRAZIL_REGION_STATES
from categories.services import category_scope_ids
from .models import Listing


def _decimal(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _get(data, key, default=None):
    return (
        data.get(key, default)
        if isinstance(data, dict)
        else getattr(data, key, default)
    )


def apply_listing_filters(qs, filters):
    q = (_get(filters, "q", "") or "").strip()
    if q:
        if connection.vendor == "postgresql":
            try:
                from django.contrib.postgres.search import (
                    SearchQuery,
                    SearchRank,
                    SearchVector,
                )

                vector = SearchVector("title", weight="A") + SearchVector(
                    "description", weight="B"
                )
                query = SearchQuery(q, search_type="websearch")
                qs = (
                    qs.annotate(search_rank=SearchRank(vector, query))
                    .filter(Q(search_rank__gte=0.05) | Q(title__icontains=q))
                    .order_by("-search_rank", "-created_at")
                )
            except Exception:
                qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))
        else:
            qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))
    category = _get(filters, "category")
    country_code = _get(filters, "country_code")
    region = (_get(filters, "region") or "").strip().upper()
    state = _get(filters, "state")
    city = _get(filters, "city")
    district = _get(filters, "district")
    condition = _get(filters, "condition")
    seller_type = _get(filters, "seller_type")
    seller_id = _get(filters, "seller_id")
    if category:
        qs = qs.filter(category_id__in=category_scope_ids(category))
    if country_code:
        qs = qs.filter(country_code__iexact=country_code)
    if region:
        qs = qs.filter(state_code__in=BRAZIL_REGION_STATES.get(region, ()))
    if state:
        qs = qs.filter(state_code__iexact=state)
    if city:
        qs = qs.filter(city__iexact=city)
    if district:
        qs = qs.filter(district__icontains=district)
    if condition:
        condition = {
            "New": "Brand New",
            "Like new": "Refurbished",
        }.get(condition, condition)
        qs = qs.filter(condition=condition)
    if seller_type:
        qs = qs.filter(seller__seller_type=seller_type)
    if seller_id:
        qs = qs.filter(seller_id=seller_id)
    if _get(filters, "verified_only", False):
        qs = qs.filter(seller__verified_at__isnull=False)
    lat, lng = validate_coordinates(
        _get(filters, "latitude"), _get(filters, "longitude")
    )
    radius = validate_radius_km(_get(filters, "radius_km"))
    if radius is not None and lat is None:
        from django.core.exceptions import ValidationError

        raise ValidationError(
            {"radius_km": "Radius search requires latitude and longitude."}
        )
    if lat is not None:
        origin = Point(lng, lat, srid=4326)
        qs = qs.exclude(location_point__isnull=True).annotate(
            distance=Distance("location_point", origin)
        )
        if radius is not None:
            qs = qs.filter(location_point__distance_lte=(origin, D(km=radius)))
    mn = _decimal(_get(filters, "min_price"))
    mx = _decimal(_get(filters, "max_price"))
    if mn is not None:
        qs = qs.filter(price__gte=mn)
    if mx is not None:
        qs = qs.filter(price__lte=mx)
    date_listed = _get(filters, "date_listed")
    days = {"today": 1, "week": 7, "month": 30}.get(date_listed)
    if days:
        qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=days))
    attrs = _get(filters, "attribute_filters") or {}
    if isinstance(attrs, dict):
        for key, value in list(attrs.items())[:20]:
            if isinstance(value, dict):
                if value.get("min") is not None:
                    qs = qs.filter(
                        attribute_values__key=key,
                        attribute_values__number_value__gte=_decimal(value["min"]),
                    )
                if value.get("max") is not None:
                    qs = qs.filter(
                        attribute_values__key=key,
                        attribute_values__number_value__lte=_decimal(value["max"]),
                    )
            elif isinstance(value, bool):
                qs = qs.filter(
                    attribute_values__key=key, attribute_values__boolean_value=value
                )
            elif value not in (None, ""):
                qs = qs.filter(
                    attribute_values__key=key,
                    attribute_values__text_value__iexact=str(value),
                )
    return qs.distinct()


def apply_listing_sort(qs, sort="relevant"):
    from promotions.models import ListingPromotion, PromotionProduct

    if sort == "distance":
        if "distance" not in qs.query.annotations:
            return qs.order_by("-created_at", "-id")
        return qs.order_by("distance", "-created_at", "-id")
    if sort == "price_asc":
        return qs.order_by("price", "-created_at", "-id")
    if sort == "price_desc":
        return qs.order_by("-price", "-created_at", "-id")
    if sort == "newest":
        return qs.order_by("-created_at", "-id")
    now = timezone.now()
    featured = ListingPromotion.objects.filter(
        listing_id=OuterRef("pk"),
        product__code__in=[
            PromotionProduct.Code.FEATURED,
            PromotionProduct.Code.TOP_SEARCH,
        ],
        cancelled_at__isnull=True,
        starts_at__lte=now,
        ends_at__gt=now,
    )
    ranked = qs.annotate(is_promoted=Exists(featured))
    ordering = ["-is_promoted"]
    if "spec_match_count" in ranked.query.annotations:
        ordering.append("-spec_match_count")
    if "search_rank" in ranked.query.annotations:
        ordering.append("-search_rank")
    if "typo_score" in ranked.query.annotations:
        ordering.append("-typo_score")
    ordering.extend(["-views", "-created_at", "-id"])
    return ranked.order_by(*ordering)
