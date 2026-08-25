from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError

from marketlift.locations import BRAZIL_STATES, normalize_brazil_state_code
from marketlift.markets.service import normalize_enabled_country_code

_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def _float(name: str, value) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError, OverflowError) as exc:
        raise ValidationError({name: "Must be a valid number."}) from exc
    if not math.isfinite(number):
        raise ValidationError({name: "Must be a finite number."})
    return number


def validate_coordinates(
    latitude, longitude, *, required: bool = False
) -> tuple[float | None, float | None]:
    lat = _float("latitude", latitude)
    lng = _float("longitude", longitude)
    if (lat is None) != (lng is None):
        raise ValidationError(
            {"location": "Latitude and longitude must be supplied together."}
        )
    if required and lat is None:
        raise ValidationError({"location": "Latitude and longitude are required."})
    if lat is None:
        return None, None
    if not -90 <= lat <= 90:
        raise ValidationError({"latitude": "Latitude must be between -90 and 90."})
    if not -180 <= lng <= 180:
        raise ValidationError({"longitude": "Longitude must be between -180 and 180."})
    return lat, lng


def validate_radius_km(value) -> float | None:
    radius = _float("radius_km", value)
    if radius is None:
        return None
    max_radius = float(getattr(settings, "MARKETLIFT_LOCATION_MAX_RADIUS_KM", 200.0))
    if radius <= 0:
        raise ValidationError({"radius_km": "Radius must be greater than zero."})
    if radius > max_radius:
        raise ValidationError({"radius_km": f"Radius cannot exceed {max_radius:g} km."})
    return radius


def normalize_country_code(value: str | None) -> str:
    code = (value or "").strip().upper()
    if not code:
        return ""
    if not _COUNTRY_RE.fullmatch(code):
        raise ValidationError(
            {"country_code": "Country code must be a two-letter ISO code."}
        )
    return code


def validate_location_strings(
    *,
    state: str,
    state_code: str,
    city: str,
    district: str = "",
    country_code: str | None = None,
) -> dict[str, str]:
    country = normalize_country_code(country_code) or settings.MARKETLIFT_MARKET_COUNTRY_CODE
    country = normalize_enabled_country_code(country)

    raw_state = (state or "").strip()
    raw_code = (state_code or "").strip().upper()
    if country == "BR":
        try:
            code = normalize_brazil_state_code(raw_code)
        except ValueError as exc:
            raise ValidationError({"state_code": str(exc)}) from exc
        raw_state = BRAZIL_STATES[code]
        raw_code = code

    values = {
        "state": raw_state,
        "state_code": raw_code,
        "city": (city or "").strip(),
        "district": (district or "").strip(),
        "country_code": country,
    }
    limits = {
        "state": 100,
        "state_code": 8,
        "city": 100,
        "district": 120,
        "country_code": 2,
    }
    errors = {}
    for name, limit in limits.items():
        if len(values[name]) > limit:
            errors[name] = f"Value cannot exceed {limit} characters."
    if not values["city"]:
        errors["city"] = "City is required."
    if errors:
        raise ValidationError(errors)
    return values
