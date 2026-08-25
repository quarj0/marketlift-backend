from __future__ import annotations

import importlib

from django.conf import settings
from marketlift.markets.service import default_country_code
from django.core.exceptions import ValidationError

from .contracts import LocationCandidate
from .validators import validate_coordinates


def _backend():
    dotted = getattr(
        settings,
        "MARKETLIFT_GEOCODER_BACKEND",
        "marketlift.location.providers.disabled.DisabledGeocoder",
    )
    module_name, class_name = dotted.rsplit(".", 1)
    return getattr(importlib.import_module(module_name), class_name)()


def geocode_locations(
    query: str, *, limit: int = 5, country_code: str | None = None
) -> list[LocationCandidate]:
    query = (query or "").strip()
    if len(query) < 2:
        raise ValidationError(
            {"q": "Location search must contain at least 2 characters."}
        )
    max_length = int(getattr(settings, "MARKETLIFT_LOCATION_QUERY_MAX_LENGTH", 160))
    if len(query) > max_length:
        raise ValidationError(
            {"q": f"Location search cannot exceed {max_length} characters."}
        )
    return _backend().geocode(
        query,
        limit=max(1, min(int(limit), 8)),
        country_code=country_code or default_country_code(),
    )


def reverse_geocode_location(latitude, longitude) -> LocationCandidate | None:
    lat, lng = validate_coordinates(latitude, longitude, required=True)
    return _backend().reverse(lat, lng)
