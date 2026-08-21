from __future__ import annotations

import hashlib
import unicodedata

import httpx
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError

from listings.models import Listing
from marketlift.locations import BRAZIL_STATES, normalize_brazil_state_code


def _normalize_query(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (value or "").strip().casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _inventory_cities(state_code: str) -> list[str]:
    return list(
        Listing.objects.public()
        .filter(state_code__iexact=state_code)
        .exclude(city="")
        .order_by("city")
        .values_list("city", flat=True)
        .distinct()[:500]
    )


def brazil_cities(state_code: str, *, query: str = "", limit: int = 80) -> list[str]:
    """Return municipality suggestions for one Brazilian state.

    The official IBGE catalogue is cached server-side so browsers do not depend
    on a third-party endpoint. Existing public inventory is a bounded fallback
    if the catalogue provider is temporarily unavailable.
    """

    try:
        code = normalize_brazil_state_code(state_code)
    except ValueError as exc:
        raise ValidationError({"state": str(exc)}) from exc

    limit = max(1, min(int(limit), 200))
    base_url = getattr(
        settings,
        "MARKETLIFT_IBGE_LOCATIONS_BASE_URL",
        "https://servicodados.ibge.gov.br/api/v1/localidades",
    ).rstrip("/")
    cache_seconds = int(
        getattr(settings, "MARKETLIFT_LOCATION_CATALOG_CACHE_SECONDS", 604800)
    )
    cache_key = "marketlift:ibge:cities:" + hashlib.sha256(code.encode()).hexdigest()
    cities = cache.get(cache_key)

    if cities is None:
        try:
            timeout = max(
                1.0,
                min(
                    float(
                        getattr(
                            settings,
                            "MARKETLIFT_LOCATION_CATALOG_TIMEOUT_SECONDS",
                            5.0,
                        )
                    ),
                    10.0,
                ),
            )
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                response = client.get(
                    f"{base_url}/estados/{code}/municipios",
                    params={"orderBy": "nome"},
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                payload = response.json()
            rows = payload if isinstance(payload, list) else []
            cities = sorted(
                {
                    str(item.get("nome") or "").strip()
                    for item in rows
                    if isinstance(item, dict) and str(item.get("nome") or "").strip()
                },
                key=_normalize_query,
            )
            if cities:
                cache.set(cache_key, cities, timeout=cache_seconds)
        except (httpx.HTTPError, ValueError, TypeError):
            cities = []

    if not cities:
        cities = _inventory_cities(code)
        # Avoid hammering the upstream catalogue when it is unavailable while
        # still refreshing much sooner than a successful official catalogue.
        if cities:
            cache.set(cache_key, cities, timeout=min(cache_seconds, 600))

    needle = _normalize_query(query)
    if needle:
        cities = [city for city in cities if needle in _normalize_query(city)]
    return cities[:limit]


def brazil_state_payload(region_code: str | None = None) -> list[dict[str, str]]:
    from marketlift.locations import BRAZIL_STATE_REGION, normalize_brazil_region_code

    region = None
    if region_code:
        try:
            region = normalize_brazil_region_code(region_code)
        except ValueError as exc:
            raise ValidationError({"region": str(exc)}) from exc
    return [
        {"code": code, "name": name, "regionCode": BRAZIL_STATE_REGION[code]}
        for code, name in BRAZIL_STATES.items()
        if not region or BRAZIL_STATE_REGION[code] == region
    ]
