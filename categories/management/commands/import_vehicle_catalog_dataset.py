from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date
from pathlib import Path
from unicodedata import normalize

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from categories.catalogs import import_category_catalog
from categories.models import Category

TARGETS = {
    "cars": "cars",
    "motorcycles": "motorcycles",
    "trucks": "trucks-commercial-vehicles",
    "buses": "buses-vans",
}
HEADER_ALIASES = {
    "vehicle_type": {
        "vehicle_type",
        "vehicle type",
        "vehicletype",
        "tipo",
        "tipo_veiculo",
        "tipo veiculo",
        "tipoveiculo",
    },
    "make": {"make", "brand", "marca"},
    "model": {"model", "modelo"},
    "year": {"year", "ano", "ano_modelo", "ano modelo", "anomodelo"},
}
VEHICLE_TYPE_ALIASES = {
    "1": "cars",
    "car": "cars",
    "cars": "cars",
    "carro": "cars",
    "carros": "cars",
    "2": "motorcycles",
    "motorcycle": "motorcycles",
    "motorcycles": "motorcycles",
    "moto": "motorcycles",
    "motos": "motorcycles",
    "3": "trucks",
    "truck": "trucks",
    "trucks": "trucks",
    "caminhao": "trucks",
    "caminhoes": "trucks",
    "bus": "buses",
    "buses": "buses",
    "onibus": "buses",
}
MAX_SOURCE_ROWS = 200000


def _clean(value) -> str:
    return " ".join(str(value or "").strip().split())


def _normalized(value) -> str:
    return (
        "".join(
            character
            for character in normalize("NFKD", _clean(value).lower())
            if not character.isspace() or character == " "
        )
        .encode("ascii", "ignore")
        .decode()
    )


def _source_columns(fieldnames: list[str] | None) -> dict[str, str]:
    available = {_normalized(name): name for name in fieldnames or []}
    columns = {}
    for canonical, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            match = available.get(_normalized(alias))
            if match:
                columns[canonical] = match
                break
    missing = sorted(set(HEADER_ALIASES) - set(columns))
    if missing:
        raise CommandError("Vehicle dataset is missing columns: " + ", ".join(missing))
    return columns


def _read_source(path: Path) -> dict[str, set[tuple[str, str, int]]]:
    if not path.is_file():
        raise CommandError(f"Vehicle catalog dataset does not exist: {path}")

    grouped: dict[str, set[tuple[str, str, int]]] = defaultdict(set)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = _source_columns(reader.fieldnames)
        for row_number, row in enumerate(reader, start=2):
            if row_number > MAX_SOURCE_ROWS + 1:
                raise CommandError(
                    f"Vehicle datasets can contain at most {MAX_SOURCE_ROWS} rows."
                )
            raw_vehicle_type = _normalized(row[columns["vehicle_type"]])
            vehicle_type = VEHICLE_TYPE_ALIASES.get(raw_vehicle_type, raw_vehicle_type)
            make = _clean(row[columns["make"]])
            model = _clean(row[columns["model"]])
            raw_year = _clean(row[columns["year"]])
            if vehicle_type not in TARGETS:
                raise CommandError(
                    f"Row {row_number}: unsupported vehicle_type '{vehicle_type}'."
                )
            try:
                year = date.today().year if raw_year == "32000" else int(raw_year)
            except ValueError as exc:
                raise CommandError(
                    f"Row {row_number}: year must be a four-digit number."
                ) from exc
            if not make or not model:
                raise CommandError(f"Row {row_number}: make and model are required.")
            if not 1886 <= year <= date.today().year:
                raise CommandError(
                    f"Row {row_number}: year {year} is outside the valid range."
                )
            grouped[vehicle_type].add((make[:120], model[:120], year))

    if not grouped:
        raise CommandError("Vehicle dataset contains no rows.")
    return grouped


def _catalog_csv(rows: set[tuple[str, str, int]]) -> str:
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
            "unit",
            "sort_order",
            "active",
        ]
    )

    makes = sorted({make for make, _, _ in rows}, key=str.casefold)
    make_values = {make: slugify(make)[:120] for make in makes}
    for index, make in enumerate(makes):
        writer.writerow(
            [
                "make",
                "Make",
                "",
                "",
                make_values[make],
                make,
                "true",
                "true",
                "true",
                "true",
                "",
                index,
                "true",
            ]
        )

    models = sorted(
        {(make, model) for make, model, _ in rows},
        key=lambda item: (item[0].casefold(), item[1].casefold()),
    )
    model_values: dict[tuple[str, str], str] = {}
    used_model_values: dict[str, tuple[str, str]] = {}
    for index, (make, model) in enumerate(models):
        value = model
        previous = used_model_values.get(value.casefold())
        if previous and previous != (make, model):
            value = f"{model} ({make})"[:120]
        used_model_values[value.casefold()] = (make, model)
        model_values[(make, model)] = value
        writer.writerow(
            [
                "model",
                "Model",
                "make",
                make_values[make],
                value,
                model,
                "true",
                "true",
                "true",
                "true",
                "",
                index,
                "true",
            ]
        )

    for index, (make, model, year) in enumerate(
        sorted(
            rows, key=lambda item: (item[0].casefold(), item[1].casefold(), -item[2])
        )
    ):
        writer.writerow(
            [
                "year",
                "Year of Manufacture",
                "model",
                model_values[(make, model)],
                str(year),
                str(year),
                "true",
                "true",
                "true",
                "true",
                "",
                index,
                "true",
            ]
        )
    return output.getvalue()


class Command(BaseCommand):
    help = (
        "Import a licensed make/model/year CSV into the vehicle category cascades. "
        "Required columns: vehicle_type, make, model, year."
    )

    def add_arguments(self, parser):
        parser.add_argument("dataset", type=Path)
        parser.add_argument(
            "--category",
            action="append",
            choices=sorted(TARGETS),
            help="Import only this vehicle type. Repeat for multiple types.",
        )
        parser.add_argument(
            "--append",
            action="store_true",
            help="Keep active catalog choices omitted from the supplied dataset.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and import inside a transaction that is rolled back.",
        )

    def handle(self, *args, **options):
        grouped = _read_source(options["dataset"])
        selected = set(options["category"] or grouped)
        missing_types = sorted(selected - set(grouped))
        if missing_types:
            raise CommandError("Dataset has no rows for: " + ", ".join(missing_types))

        with transaction.atomic():
            for vehicle_type in sorted(selected):
                slug = TARGETS[vehicle_type]
                try:
                    category = Category.objects.get(slug=slug)
                except Category.DoesNotExist as exc:
                    raise CommandError(f"Category '{slug}' does not exist.") from exc
                result = import_category_catalog(
                    category=category,
                    csv_text=_catalog_csv(grouped[vehicle_type]),
                    replace_current=not options["append"],
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{vehicle_type}: {result.rows} catalog rows, "
                        f"{result.dependencies_created} dependencies."
                    )
                )
            if options["dry_run"]:
                transaction.set_rollback(True)
                self.stdout.write(
                    self.style.WARNING("Dry run complete; changes rolled back.")
                )
