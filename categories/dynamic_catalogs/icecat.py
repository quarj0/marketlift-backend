from __future__ import annotations

import hashlib
import json
import os

import httpx
from django.core.cache import cache

DEFAULT_URL = "https://live.icecat.biz/api"
DEFAULT_TTL = 30 * 24 * 60 * 60
DEFAULT_COOLDOWN = 5 * 60


def _credentials() -> tuple[str, str, str, str] | None:
    username = os.environ.get("ICECAT_USERNAME", "").strip()
    api_token = os.environ.get("ICECAT_API_TOKEN", "").strip()
    password = os.environ.get("ICECAT_PASSWORD", "").strip()
    content_token = os.environ.get("ICECAT_CONTENT_TOKEN", "").strip()
    if not username or not api_token:
        return None
    return username, api_token, password, content_token


def lookup_product(
    *,
    brand: str | None = None,
    product_code: str | None = None,
    gtin: str | None = None,
    icecat_id: str | None = None,
) -> dict | None:
    """
    Retrieve one Icecat product data sheet.

    Icecat's JSON API is identifier-based, so this is intentionally used for
    product/specification enrichment rather than Brand -> Model discovery.
    """
    credentials = _credentials()
    if credentials is None:
        return None

    username, api_token, password, content_token = credentials
    brand = (brand or "").strip()
    product_code = (product_code or "").strip()
    gtin = (gtin or "").strip()
    icecat_id = (icecat_id or "").strip()
    if not gtin and not icecat_id and not (brand and product_code):
        return None

    language = os.environ.get("ICECAT_LANGUAGE", "EN").strip() or "EN"
    endpoint = os.environ.get("ICECAT_JSON_URL", DEFAULT_URL).strip() or DEFAULT_URL
    identifier = json.dumps(
        {
            "brand": brand,
            "credential_scope": hashlib.sha256(
                f"{username}\0{api_token}\0{content_token}".encode("utf-8")
            ).hexdigest(),
            "endpoint": endpoint,
            "product_code": product_code,
            "gtin": gtin,
            "icecat_id": icecat_id,
            "language": language,
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    cache_key = f"marketlift:icecat:product:{digest}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        return cached

    cooldown_key = "marketlift:dynamic-catalog:icecat:cooldown"
    if cache.get(cooldown_key):
        return None

    lock_key = f"marketlift:icecat:lock:{digest}"
    if not cache.add(lock_key, "1", timeout=30):
        return None

    try:
        params = {
            "lang": language,
            "shopname": username,
            "content": "",
        }
        if gtin:
            params["GTIN"] = gtin
        elif icecat_id:
            params["icecat_id"] = icecat_id
        else:
            params["Brand"] = brand
            params["ProductCode"] = product_code

        headers = {"api-token": api_token}
        if content_token:
            headers["content-token"] = content_token

        auth = httpx.BasicAuth(username, password) if password else None
        response = httpx.get(
            endpoint,
            params=params,
            headers=headers,
            auth=auth,
            timeout=httpx.Timeout(8.0),
            follow_redirects=True,
        )
        if response.status_code == 429:
            try:
                cooldown = max(
                    60, int(float(response.headers.get("Retry-After", 3600)))
                )
            except (TypeError, ValueError):
                cooldown = 3600
            cache.set(cooldown_key, "1", timeout=cooldown)
            return None
        if response.status_code >= 500:
            cache.set(cooldown_key, "1", timeout=DEFAULT_COOLDOWN)
            return None
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            return None

        try:
            payload = response.json()
        except ValueError:
            cache.set(cooldown_key, "1", timeout=DEFAULT_COOLDOWN)
            return None
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return None

        cache.set(cache_key, data, timeout=DEFAULT_TTL)
        return data
    except (httpx.TimeoutException, httpx.TransportError):
        cache.set(cooldown_key, "1", timeout=DEFAULT_COOLDOWN)
        return None
    finally:
        cache.delete(lock_key)
