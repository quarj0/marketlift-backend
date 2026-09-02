from __future__ import annotations

import hashlib

import httpx
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured, ValidationError

from marketlift.location.contracts import LocationCandidate
from marketlift.location.validators import validate_coordinates
from marketlift.markets.service import default_country_code

from .base import GeocoderBackend


def _first(components: dict, *keys: str) -> str:
    for key in keys:
        value = components.get(key)
        if value:
            return str(value).strip()
    return ""


def _state_code(components: dict) -> str:
    raw = str(components.get("state_code") or "").strip().upper()
    if raw:
        return raw[:8]
    iso = components.get("ISO_3166-2")
    values = iso if isinstance(iso, list) else [iso] if iso else []
    for value in values:
        text = str(value or "").strip().upper()
        if "-" in text:
            return text.rsplit("-", 1)[-1][:8]
    return ""


def _candidate_from_result(result: dict) -> LocationCandidate:
    components = result.get("components") or {}
    geometry = result.get("geometry") or {}
    lat, lng = validate_coordinates(geometry.get("lat"), geometry.get("lng"), required=True)
    return LocationCandidate(
        latitude=lat,
        longitude=lng,
        label=str(result.get("formatted") or "").strip()[:500],
        country_code=str(components.get("country_code") or "").strip().upper()[:2],
        country=_first(components, "country")[:120],
        state=_first(components, "state", "region", "province")[:100],
        state_code=_state_code(components),
        city=_first(components, "city", "town", "municipality", "village", "county")[:100],
        district=_first(components, "suburb", "neighbourhood", "city_district", "borough", "quarter")[:120],
        provider="opencage",
        provider_id="",
    )


class OpenCageGeocoder(GeocoderBackend):
    def __init__(self):
        self.api_key = str(getattr(settings, "OPENCAGE_API_KEY", "") or "").strip()
        if not self.api_key:
            raise ImproperlyConfigured(
                "OPENCAGE_API_KEY is required when OpenCageGeocoder is configured."
            )
        self.base_url = str(
            getattr(
                settings,
                "MARKETLIFT_OPENCAGE_BASE_URL",
                "https://api.opencagedata.com/geocode/v1/json",
            )
        ).rstrip("/")
        self.timeout = max(
            1.0,
            min(float(getattr(settings, "MARKETLIFT_GEOCODER_TIMEOUT_SECONDS", 4.0)), 10.0),
        )
        self.language = str(
            getattr(settings, "MARKETLIFT_GEOCODER_LANGUAGE", "pt-BR,en")
        ).split(",", 1)[0].strip() or "pt-BR"
        self.cache_seconds = int(
            getattr(settings, "MARKETLIFT_GEOCODER_CACHE_SECONDS", 86400)
        )

    def _request(self, params: dict) -> list[dict]:
        params = {
            **params,
            "key": self.api_key,
            "language": self.language,
            "no_annotations": 1,
            "no_record": 1,
        }
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                response = client.get(
                    self.base_url,
                    params=params,
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise ValidationError(
                {"location": "Location provider is temporarily unavailable."}
            ) from exc
        except ValueError as exc:
            raise ValidationError(
                {"location": "Location provider returned an invalid response."}
            ) from exc
        rows = payload.get("results") if isinstance(payload, dict) else None
        return [row for row in (rows or []) if isinstance(row, dict)]

    def geocode(self, query: str, *, limit: int = 5, country_code: str | None = None) -> list[LocationCandidate]:
        query = (query or "").strip()
        limit = max(1, min(int(limit), 8))
        country = (country_code or default_country_code()).strip().lower()
        if len(country) != 2:
            raise ValidationError(
                {"country_code": "Country code must be a two-letter ISO code."}
            )
        cache_key = "marketlift:geocode:opencage:" + hashlib.sha256(
            f"{self.language}|{country}|{query}|{limit}".encode()
        ).hexdigest()
        cached = cache.get(cache_key)
        if cached is not None:
            return [LocationCandidate(**item) for item in cached]
        candidates = [
            _candidate_from_result(row)
            for row in self._request({"q": query, "countrycode": country, "limit": limit})
        ]
        cache.set(cache_key, [item.__dict__ for item in candidates], timeout=self.cache_seconds)
        return candidates

    def reverse(self, latitude: float, longitude: float) -> LocationCandidate | None:
        lat, lng = validate_coordinates(latitude, longitude, required=True)
        cache_key = "marketlift:reverse:opencage:" + hashlib.sha256(
            f"{self.language}|{lat:.5f}|{lng:.5f}".encode()
        ).hexdigest()
        cached = cache.get(cache_key)
        if cached is not None:
            return LocationCandidate(**cached) if cached else None
        rows = self._request({"q": f"{lat:.6f},{lng:.6f}", "limit": 1})
        candidate = _candidate_from_result(rows[0]) if rows else None
        cache.set(cache_key, candidate.__dict__ if candidate else {}, timeout=self.cache_seconds)
        return candidate
