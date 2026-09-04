from __future__ import annotations

from datetime import date
from urllib.parse import quote

import httpx
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from categories.catalogs import import_category_catalog
from categories.management.commands.import_vehicle_catalog_dataset import (
    TARGETS,
    _catalog_csv,
    existing_vehicle_rows,
)
from categories.models import Category, CategoryField

VPIC_BASE_URL = "https://vpic.nhtsa.dot.gov/api/vehicles"
VPIC_TYPES = {
    "cars": "Passenger Car",
    "motorcycles": "Motorcycle",
    "trucks": "Truck",
    "buses": "Bus",
}


def _results(response: httpx.Response) -> list[dict]:
    response.raise_for_status()
    payload = response.json()
    results = payload.get("Results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        raise CommandError("NHTSA vPIC returned an unexpected response.")
    return results


def fetch_rows(
    client: httpx.Client,
    *,
    vehicle_type: str,
    makes: list[str],
    start_year: int,
    end_year: int,
    max_requests: int,
) -> set[tuple[str, str, int]]:
    rows: set[tuple[str, str, int]] = set()
    requests = 0
    vpic_type = quote(VPIC_TYPES[vehicle_type], safe="")
    for make in makes:
        encoded_make = quote(make, safe="")
        for year in range(start_year, end_year + 1):
            requests += 1
            if requests > max_requests:
                raise CommandError(
                    f"The requested sync exceeds --max-requests={max_requests}. "
                    "Narrow --category, --make, or the year range."
                )
            url = (
                f"{VPIC_BASE_URL}/GetModelsForMakeYear/make/{encoded_make}"
                f"/modelyear/{year}/vehicletype/{vpic_type}?format=json"
            )
            try:
                results = _results(client.get(url))
            except httpx.HTTPError as exc:
                raise CommandError(
                    f"NHTSA vPIC request failed for {make} {year}: {exc}"
                ) from exc
            for item in results:
                source_make = " ".join(str(item.get("Make_Name") or make).split())
                model = " ".join(str(item.get("Model_Name") or "").split())
                if source_make and model:
                    rows.add((source_make[:120], model[:120], year))
    return rows


def fetch_makes(client: httpx.Client, *, vehicle_type: str) -> list[str]:
    encoded_type = quote(VPIC_TYPES[vehicle_type], safe="")
    url = f"{VPIC_BASE_URL}/GetMakesForVehicleType/{encoded_type}?format=json"
    try:
        results = _results(client.get(url))
    except httpx.HTTPError as exc:
        raise CommandError(f"NHTSA vPIC make lookup failed: {exc}") from exc
    return sorted(
        {
            " ".join(str(item.get("MakeName") or "").split())
            for item in results
            if str(item.get("MakeName") or "").strip()
        },
        key=str.casefold,
    )


class Command(BaseCommand):
    help = (
        "Refresh vehicle make/model/year selectors from the public NHTSA vPIC "
        "open-data API as a global alternative to Brazil-specific catalog imports."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--category",
            action="append",
            choices=sorted(TARGETS),
            help="Vehicle type to sync. Repeat for multiple types; defaults to all.",
        )
        parser.add_argument(
            "--make",
            action="append",
            help="Only sync this make. Repeat for multiple makes.",
        )
        parser.add_argument("--start-year", type=int, default=1996)
        parser.add_argument("--end-year", type=int, default=date.today().year)
        parser.add_argument("--max-requests", type=int, default=10000)
        parser.add_argument("--dry-run", action="store_true")

    def _makes(
        self,
        client: httpx.Client,
        *,
        category: Category,
        vehicle_type: str,
        requested: list[str] | None,
    ) -> list[str]:
        if requested:
            return sorted({item.strip() for item in requested if item.strip()})
        try:
            field = category.fields.get(key="make")
        except CategoryField.DoesNotExist:
            return fetch_makes(client, vehicle_type=vehicle_type)
        makes = list(
            field.options.filter(active=True)
            .order_by("label")
            .values_list("label", flat=True)
        )
        if not makes:
            return fetch_makes(client, vehicle_type=vehicle_type)
        return makes

    def handle(self, *args, **options):
        start_year = options["start_year"]
        end_year = min(options["end_year"], date.today().year)
        if start_year < 1996 or start_year > end_year:
            raise CommandError("NHTSA model-year sync requires 1996 <= start <= end.")

        selected = options["category"] or list(TARGETS)
        with (
            httpx.Client(
                timeout=httpx.Timeout(20.0),
                headers={"User-Agent": "Marketlift catalog sync/1.0"},
            ) as client,
            transaction.atomic(),
        ):
            for vehicle_type in selected:
                slug = TARGETS[vehicle_type]
                try:
                    category = Category.objects.get(slug=slug, active=True)
                except Category.DoesNotExist as exc:
                    raise CommandError(f"Category '{slug}' does not exist.") from exc
                makes = self._makes(
                    client,
                    category=category,
                    vehicle_type=vehicle_type,
                    requested=options["make"],
                )
                rows = fetch_rows(
                    client,
                    vehicle_type=vehicle_type,
                    makes=makes,
                    start_year=start_year,
                    end_year=end_year,
                    max_requests=options["max_requests"],
                )
                if not rows:
                    raise CommandError(
                        f"NHTSA vPIC returned no {vehicle_type} models "
                        "for the selection."
                    )
                if options["make"]:
                    refreshed = {make.casefold() for make in makes}
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
                        f"{vehicle_type}: {len(makes)} makes, "
                        f"{len({(make, model) for make, model, _ in rows})} models, "
                        f"{len(rows)} model-year links, "
                        f"schema v{category.schema_version + 1}."
                    )
                )
                if result.dependencies_created < len(rows):
                    raise CommandError("Vehicle dependency import was incomplete.")

            if options["dry_run"]:
                transaction.set_rollback(True)
                self.stdout.write(
                    self.style.WARNING("Dry run complete; changes rolled back.")
                )
