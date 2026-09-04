from __future__ import annotations

import csv
import io

import httpx
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from categories.catalogs import import_category_catalog
from categories.models import Category

WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
ELECTRONICS = {
    "phones": "Q22645",  # smartphone
    "computers": "Q3962",  # laptop
    "tablets": "Q155972",  # tablet computer
    "cameras": "Q15328",  # camera
    "gaming": "Q8076",  # video game console
    "tvs-video": "Q8075",  # television set
    "printers-scanners": "Q82",  # computer printer
    "smart-watches": "Q5362345",  # smartwatch
}
ANIMAL_BREEDS = {
    "dogs": "Q39367",
    "cats": "Q43577",
}


def _bindings(response: httpx.Response) -> list[dict]:
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("results", {}).get("bindings", {})
    if not isinstance(rows, list):
        raise CommandError("Wikidata returned an unexpected response.")
    return rows


def fetch_brand_models(
    client: httpx.Client, *, class_id: str, limit: int
) -> set[tuple[str, str, str, str]]:
    query = f"""
SELECT DISTINCT ?model ?modelLabel ?brand ?brandLabel WHERE {{
  ?model wdt:P31 wd:{class_id}; wdt:P176 ?brand.
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "pt,en". }}
}}
LIMIT {limit}
"""
    try:
        rows = _bindings(
            client.get(
                WIKIDATA_ENDPOINT,
                params={"query": query, "format": "json"},
            )
        )
    except httpx.HTTPError as exc:
        raise CommandError(f"Wikidata electronics query failed: {exc}") from exc

    values = set()
    for row in rows:
        model_uri = row.get("model", {}).get("value", "")
        brand_uri = row.get("brand", {}).get("value", "")
        model = " ".join(row.get("modelLabel", {}).get("value", "").split())
        brand = " ".join(row.get("brandLabel", {}).get("value", "").split())
        model_id = model_uri.rsplit("/", 1)[-1]
        brand_id = brand_uri.rsplit("/", 1)[-1]
        if model and brand and model_id.startswith("Q") and brand_id.startswith("Q"):
            values.add((brand_id, brand[:120], model_id, model[:120]))
    return values


def fetch_breeds(
    client: httpx.Client, *, class_id: str, limit: int
) -> set[tuple[str, str]]:
    query = f"""
SELECT DISTINCT ?breed ?breedLabel WHERE {{
  ?breed wdt:P31 wd:{class_id}.
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "pt,en". }}
}}
LIMIT {limit}
"""
    try:
        rows = _bindings(
            client.get(
                WIKIDATA_ENDPOINT,
                params={"query": query, "format": "json"},
            )
        )
    except httpx.HTTPError as exc:
        raise CommandError(f"Wikidata animal-breed query failed: {exc}") from exc

    values = set()
    for row in rows:
        uri = row.get("breed", {}).get("value", "")
        label = " ".join(row.get("breedLabel", {}).get("value", "").split())
        entity_id = uri.rsplit("/", 1)[-1]
        if label and entity_id.startswith("Q"):
            values.add((entity_id, label[:120]))
    return values


def _brand_model_csv(rows: set[tuple[str, str, str, str]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "field_key",
            "field_label",
            "depends_on",
            "parent_value",
            "option_value",
            "option_label",
            "required",
            "filterable",
            "allow_custom",
            "lazy",
            "sort_order",
            "active",
        ]
    )
    brands = sorted(
        {(brand_id, brand) for brand_id, brand, _, _ in rows},
        key=lambda x: x[1].casefold(),
    )
    brand_values = {brand_id: slugify(brand)[:120] for brand_id, brand in brands}
    for index, (brand_id, brand) in enumerate(brands):
        writer.writerow(
            [
                "brand",
                "Brand",
                "",
                "",
                brand_values[brand_id],
                brand,
                "true",
                "true",
                "true",
                "true",
                index,
                "true",
            ]
        )
    for index, (brand_id, _, _model_id, model) in enumerate(
        sorted(rows, key=lambda x: (x[1].casefold(), x[3].casefold()))
    ):
        writer.writerow(
            [
                "model",
                "Model",
                "brand",
                brand_values[brand_id],
                model,
                model,
                "true",
                "true",
                "true",
                "true",
                index,
                "true",
            ]
        )
    return output.getvalue()


def _breed_csv(rows: set[tuple[str, str]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "field_key",
            "field_label",
            "option_value",
            "option_label",
            "required",
            "filterable",
            "allow_custom",
            "lazy",
            "sort_order",
            "active",
        ]
    )
    for index, (_entity_id, label) in enumerate(
        sorted(rows, key=lambda x: x[1].casefold())
    ):
        writer.writerow(
            [
                "breed_or_type",
                "Breed",
                slugify(label)[:120],
                label,
                "false",
                "true",
                "true",
                "true",
                index,
                "true",
            ]
        )
    return output.getvalue()


class Command(BaseCommand):
    help = (
        "Append CC0 Wikidata electronics brand/model and animal-breed choices "
        "to Marketlift's curated category catalogs."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--category",
            action="append",
            choices=sorted(set(ELECTRONICS) | set(ANIMAL_BREEDS)),
            help="Catalog to sync. Repeat for multiple categories; defaults to all.",
        )
        parser.add_argument("--limit", type=int, default=5000)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        selected = options["category"] or [*ELECTRONICS, *ANIMAL_BREEDS]
        limit = max(1, min(options["limit"], 10000))
        with (
            httpx.Client(
                timeout=httpx.Timeout(60.0),
                headers={
                    "User-Agent": "Marketlift catalog sync/1.0 (marketlift.com.br)"
                },
            ) as client,
            transaction.atomic(),
        ):
            for slug in selected:
                try:
                    category = Category.objects.get(slug=slug, active=True)
                except Category.DoesNotExist as exc:
                    raise CommandError(f"Category '{slug}' does not exist.") from exc

                if slug in ELECTRONICS:
                    rows = fetch_brand_models(
                        client, class_id=ELECTRONICS[slug], limit=limit
                    )
                    csv_text = _brand_model_csv(rows)
                    description = f"{len(rows)} brand/model links"
                else:
                    rows = fetch_breeds(
                        client, class_id=ANIMAL_BREEDS[slug], limit=limit
                    )
                    csv_text = _breed_csv(rows)
                    description = f"{len(rows)} breeds"

                if not rows:
                    raise CommandError(f"Wikidata returned no usable rows for {slug}.")
                import_category_catalog(
                    category=category,
                    csv_text=csv_text,
                    replace_current=False,
                )
                self.stdout.write(
                    self.style.SUCCESS(f"{slug}: appended {description}.")
                )

            if options["dry_run"]:
                transaction.set_rollback(True)
                self.stdout.write(
                    self.style.WARNING("Dry run complete; changes rolled back.")
                )
