from __future__ import annotations

import os
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

FIPE_BASE_URL = "https://fipe.parallelum.com.br/api/v2"
FIPE_TYPES = {
    "cars": "cars",
    "motorcycles": "motorcycles",
    "trucks": "trucks",
}


def _items(response: httpx.Response, *, description: str) -> list[dict]:
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise CommandError(f"FIPE returned an unexpected {description} response.")
    return payload


def _year_from_code(value: object, *, current_year: int) -> int | None:
    raw_year = str(value or "").split("-", 1)[0]
    try:
        year = current_year if raw_year == "32000" else int(raw_year)
    except ValueError:
        return None
    return year if 1886 <= year <= current_year else None


def fetch_fipe_rows(
    client: httpx.Client,
    *,
    vehicle_type: str,
    requested_brands: list[str] | None,
    max_requests: int,
    current_year: int,
) -> tuple[set[tuple[str, str, int]], set[str], int]:
    endpoint = FIPE_TYPES[vehicle_type]
    requests = 1
    try:
        brands = _items(
            client.get(f"{FIPE_BASE_URL}/{endpoint}/brands"),
            description="brand",
        )
    except httpx.HTTPError as exc:
        raise CommandError(f"FIPE brand lookup failed: {exc}") from exc

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
        requests += 1
        if requests > max_requests:
            raise CommandError(
                f"The FIPE sync exceeds --max-requests={max_requests}. "
                "Select fewer --brand values or use an API subscription token."
            )
        try:
            years = _items(
                client.get(f"{FIPE_BASE_URL}/{endpoint}/brands/{brand_code}/years"),
                description="year",
            )
        except httpx.HTTPError as exc:
            raise CommandError(
                f"FIPE year lookup failed for {brand_name}: {exc}"
            ) from exc

        for year_item in years:
            year_code = str(year_item.get("code") or "").strip()
            year = _year_from_code(year_code, current_year=current_year)
            if not year_code or year is None:
                continue
            requests += 1
            if requests > max_requests:
                raise CommandError(
                    f"The FIPE sync exceeds --max-requests={max_requests}. "
                    "Select fewer --brand values or use an API subscription token."
                )
            try:
                models = _items(
                    client.get(
                        f"{FIPE_BASE_URL}/{endpoint}/brands/{brand_code}"
                        f"/years/{year_code}/models"
                    ),
                    description="model",
                )
            except httpx.HTTPError as exc:
                raise CommandError(
                    f"FIPE model lookup failed for {brand_name} {year}: {exc}"
                ) from exc
            for model_item in models:
                model = " ".join(str(model_item.get("name") or "").split())
                if model:
                    rows.add((brand_name, model[:120], year))

    return rows, {name for _, name in selected}, requests


class Command(BaseCommand):
    help = (
        "Refresh Brazil-specific car, motorcycle, and truck make/model/year "
        "selectors from the FIPE-compatible API."
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
            default=500,
            help="Safety cap for FIPE HTTP requests (default: 500).",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        selected = options["category"] or list(FIPE_TYPES)
        max_requests = options["max_requests"]
        if max_requests < 1:
            raise CommandError("--max-requests must be greater than zero.")

        headers = {"User-Agent": "Marketlift catalog sync/1.0 (marketlift.com.br)"}
        token = os.environ.get("FIPE_API_TOKEN", "").strip()
        if token:
            headers["X-Subscription-Token"] = token

        fetched = {}
        with httpx.Client(timeout=httpx.Timeout(30.0), headers=headers) as client:
            for vehicle_type in selected:
                rows, brands, requests = fetch_fipe_rows(
                    client,
                    vehicle_type=vehicle_type,
                    requested_brands=options["brand"],
                    max_requests=max_requests,
                    current_year=date.today().year,
                )
                if not rows:
                    raise CommandError(
                        f"FIPE returned no usable {vehicle_type} model-year rows."
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
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{vehicle_type}: {len(brands)} refreshed brands, "
                        f"{len({(make, model) for make, model, _ in rows})} models, "
                        f"{len(rows)} model-year links, {requests} API requests."
                    )
                )
                if result.dependencies_created < len(rows):
                    raise CommandError("FIPE dependency import was incomplete.")

            if options["dry_run"]:
                transaction.set_rollback(True)
                self.stdout.write(
                    self.style.WARNING("Dry run complete; changes rolled back.")
                )
