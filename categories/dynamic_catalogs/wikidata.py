from __future__ import annotations

import hashlib
import os

import httpx
from django.core.cache import cache

DEFAULT_ENDPOINT = "https://query.wikidata.org/sparql"
CATEGORY_CLASSES = {
    "phones": "Q22645",
    "computers": "Q3962",
    "tablets": "Q155972",
    "cameras": "Q15328",
    "gaming": "Q8076",
    "tvs-video": "Q8075",
    "printers-scanners": "Q82",
    "smart-watches": "Q5362345",
    "audio": "Q15190726",
    "networking": "Q1546066",
    "other-electronics": "Q2858615",
    "electronics": "Q2858615",
}


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _cache_key(query: str) -> str:
    digest = hashlib.sha256(query.encode("utf-8")).hexdigest()
    return f"marketlift:dynamic-catalog:wikidata:{digest}"


def _bindings(query: str) -> list[dict] | None:
    cached = cache.get(_cache_key(query))
    if isinstance(cached, list):
        return cached

    cooldown_key = "marketlift:dynamic-catalog:wikidata:cooldown"
    if cache.get(cooldown_key):
        return None

    lock_key = _cache_key("lock:" + query)
    if not cache.add(lock_key, "1", timeout=30):
        return None

    endpoint = os.environ.get("WIKIDATA_SPARQL_ENDPOINT", DEFAULT_ENDPOINT)
    try:
        try:
            response = httpx.get(
                endpoint,
                params={"query": query, "format": "json"},
                headers={
                    "User-Agent": "Marketlift dynamic catalog/1.0 (marketlift.com.br)"
                },
                timeout=httpx.Timeout(8.0),
                follow_redirects=True,
            )
        except (httpx.TimeoutException, httpx.TransportError):
            cache.set(cooldown_key, "1", timeout=300)
            return None

        if response.status_code == 429:
            retry_after = _int_env("DYNAMIC_CATALOG_PROVIDER_COOLDOWN_SECONDS", 3600)
            try:
                retry_after = max(
                    60, int(float(response.headers.get("Retry-After", retry_after)))
                )
            except (TypeError, ValueError):
                pass
            cache.set(cooldown_key, "1", timeout=retry_after)
            return None
        if response.status_code >= 500:
            cache.set(cooldown_key, "1", timeout=300)
            return None
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            return None

        payload = response.json()
        rows = payload.get("results", {}).get("bindings", [])
        if not isinstance(rows, list):
            return None
        ttl = _int_env(
            "DYNAMIC_CATALOG_WIKIDATA_TTL_SECONDS", 30 * 24 * 60 * 60
        )
        cache.set(_cache_key(query), rows, timeout=ttl)
        return rows
    finally:
        cache.delete(lock_key)


def brands_for_category(class_id: str, limit: int = 250) -> list[dict] | None:
    limit = max(1, min(int(limit), 500))
    query = f"""
SELECT DISTINCT ?brand ?brandLabel WHERE {{
  ?model wdt:P31/wdt:P279* wd:{class_id};
         wdt:P176 ?brand.
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "pt,en". }}
}}
ORDER BY ?brandLabel
LIMIT {limit}
"""
    rows = _bindings(query)
    if rows is None:
        return None

    result = []
    seen = set()
    for row in rows:
        uri = row.get("brand", {}).get("value", "")
        entity_id = uri.rsplit("/", 1)[-1]
        label = " ".join(row.get("brandLabel", {}).get("value", "").split())
        key = label.casefold()
        if entity_id.startswith("Q") and label and key not in seen:
            seen.add(key)
            result.append({"id": entity_id, "name": label[:120]})
    return result


def models_for_brand(
    class_id: str, brand_id: str, limit: int = 250
) -> list[dict] | None:
    if not brand_id.startswith("Q"):
        return []
    limit = max(1, min(int(limit), 500))
    query = f"""
SELECT DISTINCT ?model ?modelLabel WHERE {{
  ?model wdt:P31/wdt:P279* wd:{class_id};
         wdt:P176 wd:{brand_id}.
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "pt,en". }}
}}
ORDER BY ?modelLabel
LIMIT {limit}
"""
    rows = _bindings(query)
    if rows is None:
        return None

    result = []
    seen = set()
    for row in rows:
        uri = row.get("model", {}).get("value", "")
        entity_id = uri.rsplit("/", 1)[-1]
        label = " ".join(row.get("modelLabel", {}).get("value", "").split())
        key = label.casefold()
        if entity_id.startswith("Q") and label and key not in seen:
            seen.add(key)
            result.append({"id": entity_id, "name": label[:120]})
    return result
