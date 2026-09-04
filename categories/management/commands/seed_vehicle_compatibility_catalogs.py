from __future__ import annotations

import csv
import io

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from categories.catalogs import import_category_catalog
from categories.models import Category, CategoryField, CategoryFieldOptionDependency

TARGETS = {
    "vehicle-parts": {
        "type_field": "part_type",
        "type_label": "Part type",
        "types": (
            "Engine",
            "Transmission",
            "Brakes",
            "Suspension",
            "Steering",
            "Electrical",
            "Cooling",
            "Exhaust",
            "Body",
            "Interior",
            "Lighting",
            "Wheels and tires",
        ),
    },
    "vehicle-accessories": {
        "type_field": "accessory_type",
        "type_label": "Accessory type",
        "types": (
            "Audio and multimedia",
            "Security",
            "Interior accessory",
            "Exterior accessory",
            "Lighting",
            "Cargo and towing",
            "Cleaning and care",
            "Tools and emergency",
        ),
    },
}
PART_BRANDS = (
    "Bosch",
    "Cofap",
    "Continental",
    "Denso",
    "JBL",
    "Mahle",
    "Mann-Filter",
    "Magneti Marelli",
    "Monroe",
    "Nakata",
    "NGK",
    "Pioneer",
    "SKF",
    "Thule",
    "TRW",
    "Valeo",
)


def _catalog_csv(*, source: Category, spec: dict) -> str:
    try:
        make_field = source.fields.get(key="make")
        model_field = source.fields.get(key="model")
    except CategoryField.DoesNotExist as exc:
        raise CommandError("Import the cars make/model catalog first.") from exc

    make_options = list(
        make_field.options.filter(active=True).order_by("sort_order", "label")
    )
    model_options = list(
        model_field.options.filter(active=True).order_by("sort_order", "label")
    )
    dependencies = CategoryFieldOptionDependency.objects.filter(
        option__field=model_field,
        parent_option__field=make_field,
    ).select_related("option", "parent_option")
    parent_values: dict[str, set[str]] = {}
    for dependency in dependencies:
        parent_values.setdefault(dependency.option.value, set()).add(
            dependency.parent_option.value
        )

    if not make_options or not model_options or not parent_values:
        raise CommandError("The cars catalog has no active make/model dependencies.")

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
    for index, label in enumerate(spec["types"]):
        writer.writerow(
            [
                spec["type_field"],
                spec["type_label"],
                "",
                "",
                "",
                label,
                "true",
                "true",
                "true",
                "false",
                "",
                index,
                "true",
            ]
        )
    for index, label in enumerate(PART_BRANDS):
        writer.writerow(
            [
                "brand",
                "Brand",
                "",
                "",
                "",
                label,
                "false",
                "true",
                "true",
                "true",
                "",
                index,
                "true",
            ]
        )
    for option in make_options:
        writer.writerow(
            [
                "compatible_make",
                "Compatible make",
                "",
                "",
                option.value,
                option.label,
                "false",
                "true",
                "true",
                "true",
                "",
                option.sort_order,
                "true",
            ]
        )
    for option in model_options:
        for parent_value in sorted(parent_values.get(option.value, ())):
            writer.writerow(
                [
                    "compatible_model",
                    "Compatible model",
                    "compatible_make",
                    parent_value,
                    option.value,
                    option.label,
                    "false",
                    "true",
                    "true",
                    "true",
                    "",
                    option.sort_order,
                    "true",
                ]
            )
    return output.getvalue()


class Command(BaseCommand):
    help = "Build vehicle-part and accessory compatibility selectors from the cars catalog."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and import inside a transaction that is rolled back.",
        )

    def handle(self, *args, **options):
        try:
            source = Category.objects.get(slug="cars")
        except Category.DoesNotExist as exc:
            raise CommandError("Category 'cars' does not exist.") from exc

        with transaction.atomic():
            for slug, spec in TARGETS.items():
                try:
                    target = Category.objects.get(slug=slug)
                except Category.DoesNotExist as exc:
                    raise CommandError(f"Category '{slug}' does not exist.") from exc
                result = import_category_catalog(
                    category=target,
                    csv_text=_catalog_csv(source=source, spec=spec),
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{slug}: {result.rows} rows, "
                        f"{result.dependencies_created} dependencies."
                    )
                )
            if options["dry_run"]:
                transaction.set_rollback(True)
                self.stdout.write(
                    self.style.WARNING("Dry run complete; changes rolled back.")
                )
