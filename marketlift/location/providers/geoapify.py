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


def _first(properties: dict, *keys: str) -> str:
    for key in keys:
        value = properties.get(key)
        if value:
            return str(value).strip()
    return ""


def _state_code(properties: dict) -> str:
    raw = str(
        properties.get("state_code")
        or properties.get("state_code_2")
        or ""
    ).strip().upper()
    if raw:
        if "-" in raw:
            raw = raw.rsplit("-", 1)[-1]
        return raw[:8]
    for key in ("iso3166_2", "iso3166-2"):
        value = properties.get(key)
        if value:
            text = str(value).strip().upper()
            if "-" in text:
                return text.rsplit("-", 1)[-1][:8]
    return ""


def _candidate_from_result(result: dict) -> LocationCandidate:
    properties = result.get("properties") if isinstance(result.get("properties"), dict) else result
    lat, lng = validate_coordinates(
        properties.get("lat"),
        properties.get("lon") if properties.get("lon") is not None else properties.get("lng"),
        required=True,
    )
    return LocationCandidate(
        latitude=lat,
        longitude=lng,
        label=str(
            properties.get("formatted")
            or properties.get("address_line2")
            or properties.get("name")
            or ""
        ).strip()[:500],
        country_code=str(properties.get("country_code") or "").strip().upper()[:2],
        country=_first(properties, "country")[:120],
        state=_first(properties, "state", "state_district", "county")[:100],
        state_code=_state_code(properties),
        city=_first(
            properties,
            "city",
            "town",
            "village",
            "municipality",
            "county",
        )[:100],
        district=_first(
            properties,
            "suburb",
            "district",
            "neighbourhood",
            "quarter",
            "city_district",
        )[:120],
        provider="geoapify",
        provider_id=str(properties.get("place_id") or "").strip()[:200],
    )


class GeoapifyGeocoder(GeocoderBackend):
    def __init__(self):
        self.api_key = str(getattr(settings, "GEOAPIFY_API_KEY", "") or "").strip()
        if not self.api_key:
            raise ImproperlyConfigured(
                "GEOAPIFY_API_KEY is required when GeoapifyGeocoder is configured."
            )
        self.base_url = str(
            getattr(
                settings,
                "MARKETLIFT_GEOAPIFY_BASE_URL",
                "https://api.geoapify.com/v1/geocode",
            )
        ).rstrip("/")
        self.timeout = max(
            1.0,
            min(
                float(getattr(settings, "MARKETLIFT_GEOCODER_TIMEOUT_SECONDS", 4.0)),
                10.0,
            ),
        )
        configured_language = str(
            getattr(settings, "MARKETLIFT_GEOCODER_LANGUAGE", "pt-BR,en")
        )
        self.language = (
            configured_language.split(",", 1)[0].split("-", 1)[0].strip().lower()
            or "pt"
        )
        self.cache_seconds = int(
            getattr(settings, "MARKETLIFT_GEOCODER_CACHE_SECONDS", 86400)
        )

    def _request(self, path: str, params: dict) -> list[dict]:
        request_params = {
            **params,
            "apiKey": self.api_key,
            "format": "json",
            "lang": self.language,
        }
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                response = client.get(
                    f"{self.base_url}/{path}",
                    params=request_params,
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

    def geocode(
        self, query: str, *, limit: int = 5, country_code: str | None = None
    ) -> list[LocationCandidate]:
        query = (query or "").strip()
        limit = max(1, min(int(limit), 8))
        country = (country_code or default_country_code()).strip().lower()
        if len(country) != 2:
            raise ValidationError(
                {"country_code": "Country code must be a two-letter ISO code."}
            )
        cache_key = "marketlift:geocode:geoapify:" + hashlib.sha256(
            f"{self.language}|{country}|{query}|{limit}".encode()
        ).hexdigest()
        cached = cache.get(cache_key)
        if cached is not None:
            return [LocationCandidate(**item) for item in cached]
        rows = self._request(
            "search",
            {
                "text": query,
                "filter": f"countrycode:{country}",
                "limit": limit,
            },
        )
        candidates = [_candidate_from_result(row) for row in rows]
        cache.set(
            cache_key,
            [item.__dict__ for item in candidates],
            timeout=self.cache_seconds,
        )
        return candidates

    def reverse(self, latitude: float, longitude: float) -> LocationCandidate | None:
        lat, lng = validate_coordinates(latitude, longitude, required=True)
        cache_key = "marketlift:reverse:geoapify:" + hashlib.sha256(
            f"{self.language}|{lat:.5f}|{lng:.5f}".encode()
        ).hexdigest()
        cached = cache.get(cache_key)
        if cached is not None:
            return LocationCandidate(**cached) if cached else None
        rows = self._request(
            "reverse",
            {
                "lat": lat,
                "lon": lng,
                "limit": 1,
            },
        )
        candidate = _candidate_from_result(rows[0]) if rows else None
        cache.set(
            cache_key,
            candidate.__dict__ if candidate else {},
            timeout=self.cache_seconds,
        )
        return candidate
