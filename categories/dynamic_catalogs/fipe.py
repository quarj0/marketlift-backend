from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from functools import lru_cache
from pathlib import Path

import httpx
from django.conf import settings
from django.core.cache import cache

DEFAULT_BASE_URL = "https://fipe.parallelum.com.br/api/v2"
VEHICLE_SCOPES = {
    "cars": "cars",
    "motorcycles": "motorcycles",
    "trucks-commercial-vehicles": "trucks",
    "buses-vans": "trucks",
}
BRAND_SNAPSHOT = (
    Path(__file__).resolve().parents[1] / "catalog_data" / "fipe_brands_2026_09_07.json"
)
BRAND_ALIASES = {
    "caoa changan": ("caoa-changan", "CAOA Changan"),
    "caoa chery": ("caoa-chery", "CAOA Chery"),
    "caoa chery/chery": ("chery", "Chery"),
    "gm - chevrolet": ("chevrolet", "Chevrolet"),
    "kia motors": ("kia", "Kia"),
    "vw - volkswagen": ("volkswagen", "Volkswagen"),
}


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _token() -> str:
    return (
        os.environ.get("FIPE_API_TOKEN", "").strip()
        or os.environ.get("FIPE_API_KEY", "").strip()
        or os.environ.get("FIPE_TOKEN", "").strip()
    )


def _cache_key(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"marketlift:dynamic-catalog:{prefix}:{digest}"


def _retry_after(response: httpx.Response) -> int:
    fallback = _int_env("DYNAMIC_CATALOG_PROVIDER_COOLDOWN_SECONDS", 3600)
    try:
        return max(60, int(float(response.headers.get("Retry-After", fallback))))
    except (TypeError, ValueError):
        return fallback


def _enabled() -> bool:
    return getattr(settings, "MARKETLIFT_MARKET_COUNTRY_CODE", "BR") == "BR"


def _items(path: str) -> list[dict] | None:
    if not _enabled():
        return None

    base_url = os.environ.get("FIPE_API_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    url = f"{base_url}/{path.lstrip('/')}"
    data_key = _cache_key("fipe:data", url)
    cached = cache.get(data_key)
    if isinstance(cached, list):
        return cached

    cooldown_key = "marketlift:dynamic-catalog:fipe:cooldown"
    if cache.get(cooldown_key):
        return None

    lock_key = _cache_key("fipe:lock", url)
    if not cache.add(lock_key, "1", timeout=30):
        return None

    headers = {"User-Agent": "Marketlift dynamic catalog/1.0 (marketlift.com.br)"}
    token = _token()
    if token:
        headers["X-Subscription-Token"] = token

    try:
        try:
            response = httpx.get(
                url,
                headers=headers,
                timeout=httpx.Timeout(7.0),
                follow_redirects=True,
            )
        except (httpx.TimeoutException, httpx.TransportError):
            cache.set(cooldown_key, "1", timeout=300)
            return None

        if response.status_code == 429:
            cache.set(cooldown_key, "1", timeout=_retry_after(response))
            return None
        if response.status_code >= 500:
            cache.set(cooldown_key, "1", timeout=300)
            return None
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            return None

        payload = response.json()
        if not isinstance(payload, list):
            return None

        ttl = _int_env("DYNAMIC_CATALOG_FIPE_TTL_SECONDS", 30 * 24 * 60 * 60)
        cache.set(data_key, payload, timeout=ttl)
        return payload
    finally:
        cache.delete(lock_key)


@lru_cache(maxsize=3)
def _snapshot_brands(scope: str) -> tuple[tuple[str, str], ...]:
    try:
        payload = json.loads(BRAND_SNAPSHOT.read_text(encoding="utf-8"))
        rows = payload["scopes"][scope]
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return ()

    result = []
    seen = set()
    for item in rows:
        code = str(item.get("code") or "").strip()
        raw_name = " ".join(str(item.get("name") or "").split())
        value, name = BRAND_ALIASES.get(
            raw_name.casefold(),
            ("", raw_name),
        )
        key = value or name.casefold()
        if code and name and key not in seen:
            seen.add(key)
            result.append((code, name))
    return tuple(sorted(result, key=lambda item: item[1].casefold()))


def brands(scope: str) -> list[dict] | None:
    """Return the bundled FIPE make index without delaying public requests."""
    snapshot = _snapshot_brands(scope)
    if not snapshot:
        return _items(f"{scope}/brands")
    return [{"code": code, "name": name} for code, name in snapshot]


def models(scope: str, brand_code: str) -> list[dict] | None:
    return _items(f"{scope}/brands/{brand_code}/models")


def years(scope: str, brand_code: str, model_code: str) -> list[dict] | None:
    return _items(f"{scope}/brands/{brand_code}/models/{model_code}/years")


def year_from_code(value: object) -> int | None:
    raw_year = str(value or "").split("-", 1)[0]
    current_year = date.today().year
    try:
        year = current_year if raw_year == "32000" else int(raw_year)
    except ValueError:
        return None
    return year if 1886 <= year <= current_year + 1 else None
