from __future__ import annotations

import hashlib

import httpx
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError

from marketlift.location.contracts import LocationCandidate
from marketlift.location.validators import validate_coordinates

from .base import GeocoderBackend


def _first(address: dict, *keys: str) -> str:
    for key in keys:
        value = address.get(key)
        if value:
            return str(value).strip()
    return ""


def _state_code(address: dict) -> str:
    for key, value in address.items():
        if key.casefold().startswith("iso3166-2") and value:
            raw = str(value).strip().upper()
            if "-" in raw:
                return raw.rsplit("-", 1)[-1][:8]
    return str(address.get("state_code") or "").strip().upper()[:8]


def _candidate_from_payload(payload: dict) -> LocationCandidate:
    address = payload.get("address") or {}
    lat, lng = validate_coordinates(
        payload.get("lat"), payload.get("lon"), required=True
    )
    provider_id = ""
    if payload.get("osm_type") and payload.get("osm_id"):
        provider_id = f"{payload['osm_type']}:{payload['osm_id']}"
    return LocationCandidate(
        latitude=lat,
        longitude=lng,
        label=str(payload.get("display_name") or "").strip()[:500],
        country_code=str(address.get("country_code") or "").strip().upper()[:2],
        country=_first(address, "country")[:120],
        state=_first(address, "state", "region", "province")[:100],
        state_code=_state_code(address),
        city=_first(address, "city", "town", "municipality", "village", "county")[:100],
        district=_first(
            address, "suburb", "neighbourhood", "city_district", "borough", "quarter"
        )[:120],
        provider="nominatim",
        provider_id=provider_id,
    )


class NominatimGeocoder(GeocoderBackend):
    def __init__(self):
        self.base_url = getattr(
            settings,
            "MARKETLIFT_NOMINATIM_BASE_URL",
            "https://nominatim.openstreetmap.org",
        ).rstrip("/")
        self.timeout = max(
            1.0,
            min(
                float(getattr(settings, "MARKETLIFT_GEOCODER_TIMEOUT_SECONDS", 4.0)),
                10.0,
            ),
        )
        self.user_agent = getattr(
            settings, "MARKETLIFT_GEOCODER_USER_AGENT", "Marketlift/0.1 development"
        )
        self.language = getattr(settings, "MARKETLIFT_GEOCODER_LANGUAGE", "pt-BR,en")
        self.cache_seconds = int(
            getattr(settings, "MARKETLIFT_GEOCODER_CACHE_SECONDS", 86400)
        )

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept-Language": self.language,
            "Accept": "application/json",
        }

    def _throttle(self):
        # The public Nominatim service asks clients to stay at or below one request
        # per second. Redis-backed cache.add makes this limit process-independent.
        if self.base_url == "https://nominatim.openstreetmap.org":
            if not cache.add("marketlift:geocoder:nominatim:global", "1", timeout=1):
                raise ValidationError(
                    {"location": "Location resolver is busy; retry in a moment."}
                )

    def _request(self, path: str, params: dict) -> object:
        self._throttle()
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                response = client.get(
                    f"{self.base_url}{path}", params=params, headers=self._headers()
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            raise ValidationError(
                {"location": "Location provider is temporarily unavailable."}
            ) from exc
        except ValueError as exc:
            raise ValidationError(
                {"location": "Location provider returned an invalid response."}
            ) from exc

    def geocode(self, query: str, *, limit: int = 5) -> list[LocationCandidate]:
        query = (query or "").strip()
        limit = max(1, min(int(limit), 8))
        cache_key = (
            "marketlift:geocode:"
            + hashlib.sha256(f"{self.language}|{query}|{limit}".encode()).hexdigest()
        )
        cached = cache.get(cache_key)
        if cached is not None:
            return [LocationCandidate(**item) for item in cached]
        payload = self._request(
            "/search",
            {"q": query, "format": "jsonv2", "addressdetails": 1, "limit": limit, "countrycodes": "br"},
        )
        rows = payload if isinstance(payload, list) else []
        candidates = [
            _candidate_from_payload(row) for row in rows if isinstance(row, dict)
        ]
        cache.set(
            cache_key,
            [item.__dict__ for item in candidates],
            timeout=self.cache_seconds,
        )
        return candidates

    def reverse(self, latitude: float, longitude: float) -> LocationCandidate | None:
        lat, lng = validate_coordinates(latitude, longitude, required=True)
        cache_key = (
            "marketlift:reverse:"
            + hashlib.sha256(
                f"{self.language}|{lat:.5f}|{lng:.5f}".encode()
            ).hexdigest()
        )
        cached = cache.get(cache_key)
        if cached is not None:
            return LocationCandidate(**cached) if cached else None
        payload = self._request(
            "/reverse",
            {
                "lat": lat,
                "lon": lng,
                "format": "jsonv2",
                "addressdetails": 1,
                "zoom": 18,
            },
        )
        candidate = (
            _candidate_from_payload(payload)
            if isinstance(payload, dict) and payload.get("lat")
            else None
        )
        cache.set(
            cache_key,
            candidate.__dict__ if candidate else {},
            timeout=self.cache_seconds,
        )
        return candidate
