from __future__ import annotations

import os
import time
from datetime import date

import httpx
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from categories.catalogs import import_category_catalog
from categories.management.commands.import_vehicle_catalog_dataset import (
    TARGETS,
    _catalog_csv,
    existing_vehicle_rows,
)
from categories.models import Category

FIPE_BASE_URL = os.environ.get(
    "FIPE_API_BASE_URL", "https://fipe.parallelum.com.br/api/v2"
).rstrip("/")
FIPE_TYPES = {
    "cars": "cars",
    "motorcycles": "motorcycles",
    "trucks": "trucks",
    # FIPE exposes trucks/microbuses as one dataset. Marketlift keeps
    # buses/vans as a user-facing category and uses that catalog with
    # "Other / Not listed" available for vans classified elsewhere by FIPE.
    "buses": "trucks",
}
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def _items(response: httpx.Response, *, description: str) -> list[dict]:
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise CommandError(f"FIPE returned an unexpected {description} response.")
    return payload


def _fetch_items(
    client: httpx.Client,
    url: str,
    *,
    description: str,
    failure_context: str,
    request_retries: int,
    retry_backoff: float,
) -> tuple[list[dict], int]:
    attempts = 0
    while True:
        attempts += 1
        try:
            return _items(client.get(url), description=description), attempts
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code in RETRYABLE_STATUS_CODES
            if not retryable or attempts > request_retries:
                raise CommandError(f"{failure_context}: {exc}") from exc
            retry_after = exc.response.headers.get("Retry-After", "")
            try:
                delay = max(float(retry_after), 0.0)
            except ValueError:
                delay = retry_backoff * (2 ** (attempts - 1))
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempts > request_retries:
                raise CommandError(f"{failure_context}: {exc}") from exc
            delay = retry_backoff * (2 ** (attempts - 1))
        time.sleep(min(delay, 30.0))


def _year_from_code(value: object, *, current_year: int) -> int | None:
    raw_year = str(value or "").split("-", 1)[0]
    try:
        year = current_year if raw_year == "32000" else int(raw_year)
    except ValueError:
        return None
    # Brazilian model years commonly appear one calendar year ahead
    # (for example a 2027 model during 2026), so preserve next-model-year data.
    return year if 1886 <= year <= current_year + 1 else None


def fetch_fipe_rows(
    client: httpx.Client,
    *,
    vehicle_type: str,
    requested_brands: list[str] | None,
    max_requests: int,
    current_year: int,
    request_retries: int = 4,
    retry_backoff: float = 1.0,
) -> tuple[set[tuple[str, str, int]], set[str], int]:
    endpoint = FIPE_TYPES[vehicle_type]
    requests = 0
    brands, attempts = _fetch_items(
        client,
        f"{FIPE_BASE_URL}/{endpoint}/brands",
        description="brand",
        failure_context="FIPE brand lookup failed",
        request_retries=min(request_retries, max_requests - 1),
        retry_backoff=retry_backoff,
    )
    requests += attempts

    requested = {
        item.strip().casefold() for item in requested_brands or [] if item.strip()
    }
    selected = []
    for item in brands:
        code = str(item.get("code") or "").strip()
        name = " ".join(str(item.get("name") or "").split())
        if code and name and (not requested or name.casefold() in requested):
            selected.append((code, name[:120]))

    if requested:
        found = {name.casefold() for _, name in selected}
        missing = sorted(requested - found)
        if missing:
            raise CommandError("FIPE has no matching brands: " + ", ".join(missing))
    if not selected:
        raise CommandError(f"FIPE returned no usable {vehicle_type} brands.")

    rows: set[tuple[str, str, int]] = set()
    for brand_code, brand_name in selected:
        if requests >= max_requests:
            raise CommandError(
                f"The FIPE sync exceeds --max-requests={max_requests}. "
                "Select fewer --brand values or use an API subscription token."
            )
        years, attempts = _fetch_items(
            client,
            f"{FIPE_BASE_URL}/{endpoint}/brands/{brand_code}/years",
            description="year",
            failure_context=f"FIPE year lookup failed for {brand_name}",
            request_retries=min(request_retries, max_requests - requests - 1),
            retry_backoff=retry_backoff,
        )
        requests += attempts

        for year_item in years:
            year_code = str(year_item.get("code") or "").strip()
            year = _year_from_code(year_code, current_year=current_year)
            if not year_code or year is None:
                continue
            if requests >= max_requests:
                raise CommandError(
                    f"The FIPE sync exceeds --max-requests={max_requests}. "
                    "Select fewer --brand values or use an API subscription token."
                )
            models, attempts = _fetch_items(
                client,
                f"{FIPE_BASE_URL}/{endpoint}/brands/{brand_code}"
                f"/years/{year_code}/models",
                description="model",
                failure_context=f"FIPE model lookup failed for {brand_name} {year}",
                request_retries=min(request_retries, max_requests - requests - 1),
                retry_backoff=retry_backoff,
            )
            requests += attempts
            for model_item in models:
                model = " ".join(str(model_item.get("name") or "").split())
                if model:
                    rows.add((brand_name, model[:120], year))

    return rows, {name for _, name in selected}, requests


class Command(BaseCommand):
    help = (
        "Refresh Brazil-specific car, motorcycle, truck, and bus/van "
        "make/model/year selectors from the FIPE-compatible API."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--category",
            action="append",
            choices=sorted(FIPE_TYPES),
            help="Vehicle type to sync. Repeat for multiple types; defaults to all.",
        )
        parser.add_argument(
            "--brand",
            action="append",
            help=(
                "Refresh one exact brand name while retaining other catalog rows. "
                "Repeat for multiple brands."
            ),
        )
        parser.add_argument(
            "--max-requests",
            type=int,
            default=None,
            help=(
                "Safety cap for FIPE HTTP requests. Defaults to 500 without "
                "a token, or FIPE_SYNC_MAX_REQUESTS/10000 when authenticated."
            ),
        )
        parser.add_argument(
            "--request-retries",
            type=int,
            default=4,
            help="Retries per FIPE request after transient failures (default: 4).",
        )
        parser.add_argument(
            "--retry-backoff",
            type=float,
            default=1.0,
            help="Initial retry delay in seconds, doubled per attempt (default: 1).",
        )
        parser.add_argument(
            "--allow-full-sync",
            action="store_true",
            help=(
                "Explicitly allow a full FIPE crawl. Normal Marketlift operation "
                "hydrates make/model/year branches on demand and does not need this."
            ),
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        selected = options["category"] or list(FIPE_TYPES)
        if not options["brand"] and not options["allow_full_sync"]:
            raise CommandError(
                "Full FIPE sync is disabled by default because it can exhaust the "
                "provider quota. Marketlift now hydrates vehicle selectors on demand. "
                "Use --brand for a targeted warm-up, or --allow-full-sync explicitly."
            )
        token = (
            os.environ.get("FIPE_API_TOKEN", "").strip()
            or os.environ.get("FIPE_API_KEY", "").strip()
            or os.environ.get("FIPE_TOKEN", "").strip()
        )
        max_requests = options["max_requests"]
        if max_requests is None:
            configured_limit = os.environ.get("FIPE_SYNC_MAX_REQUESTS", "").strip()
            if configured_limit:
                try:
                    max_requests = int(configured_limit)
                except ValueError as exc:
                    raise CommandError(
                        "FIPE_SYNC_MAX_REQUESTS must be a positive integer."
                    ) from exc
            else:
                max_requests = 10000 if token else 500
        if max_requests < 1:
            raise CommandError("--max-requests must be greater than zero.")
        request_retries = options["request_retries"]
        if request_retries < 0:
            raise CommandError("--request-retries cannot be negative.")
        retry_backoff = options["retry_backoff"]
        if retry_backoff < 0:
            raise CommandError("--retry-backoff cannot be negative.")

        headers = {"User-Agent": "Marketlift catalog sync/1.0 (marketlift.com.br)"}
        if token:
            headers["X-Subscription-Token"] = token

        fetched = {}
        fetched_by_endpoint = {}
        with httpx.Client(timeout=httpx.Timeout(30.0), headers=headers) as client:
            for vehicle_type in selected:
                endpoint = FIPE_TYPES[vehicle_type]
                cached = fetched_by_endpoint.get(endpoint)
                if cached is not None:
                    cached_rows, cached_brands, _ = cached
                    fetched[vehicle_type] = (
                        set(cached_rows),
                        set(cached_brands),
                        0,
                    )
                    continue

                rows, brands, requests = fetch_fipe_rows(
                    client,
                    vehicle_type=vehicle_type,
                    requested_brands=options["brand"],
                    max_requests=max_requests,
                    current_year=date.today().year,
                    request_retries=request_retries,
                    retry_backoff=retry_backoff,
                )
                if not rows:
                    raise CommandError(
                        f"FIPE returned no usable {vehicle_type} model-year rows."
                    )
                fetched_by_endpoint[endpoint] = (
                    set(rows),
                    set(brands),
                    requests,
                )
                fetched[vehicle_type] = (rows, brands, requests)

        with transaction.atomic():
            for vehicle_type in selected:
                slug = TARGETS[vehicle_type]
                try:
                    category = Category.objects.get(slug=slug, active=True)
                except Category.DoesNotExist as exc:
                    raise CommandError(f"Category '{slug}' does not exist.") from exc

                rows, brands, requests = fetched[vehicle_type]
                refreshed_rows = set(rows)
                if options["brand"]:
                    refreshed = {name.casefold() for name in brands}
                    rows |= {
                        row
                        for row in existing_vehicle_rows(category)
                        if row[0].casefold() not in refreshed
                    }

                result = import_category_catalog(
                    category=category,
                    csv_text=_catalog_csv(rows),
                    replace_current=True,
                )
                refreshed_models = len(
                    {(make, model) for make, model, _ in refreshed_rows}
                )
                total_models = len({(make, model) for make, model, _ in rows})
                brand_word = "brand" if len(brands) == 1 else "brands"
                if options["brand"]:
                    summary = (
                        f"{vehicle_type}: refreshed {len(brands)} {brand_word} with "
                        f"{refreshed_models} models and "
                        f"{len(refreshed_rows)} model-year links; "
                        f"catalog total is {total_models} models and "
                        f"{len(rows)} model-year links; {requests} API requests."
                    )
                else:
                    summary = (
                        f"{vehicle_type}: refreshed {len(brands)} {brand_word} with "
                        f"{total_models} models and {len(rows)} model-year links; "
                        f"{requests} API requests."
                    )
                self.stdout.write(
                    self.style.SUCCESS(summary)
                )
                if result.dependencies_created < len(rows):
                    raise CommandError("FIPE dependency import was incomplete.")

            if options["dry_run"]:
                transaction.set_rollback(True)
                self.stdout.write(
                    self.style.WARNING("Dry run complete; changes rolled back.")
                )
