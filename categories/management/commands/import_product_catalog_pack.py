
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from categories.catalogs import import_category_catalog
from categories.models import Category


PACKS = {
    "phones": "phones.csv",
    "computers": "computers.csv",
    "vehicles": "vehicles.csv",
    "electronics": "electronics.csv",
}


class Command(BaseCommand):
    help = (
        "Import Marketlift curated product catalogs into category-dependent "
        "listing fields while preserving historical listing values."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--category",
            action="append",
            choices=sorted(PACKS),
            help="Import only this category. Repeat for multiple categories.",
        )
        parser.add_argument(
            "--append",
            action="store_true",
            help=(
                "Keep existing active choices omitted from this pack. "
                "By default omitted choices for imported fields are deactivated."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and show counts, then roll back all changes.",
        )

    def handle(self, *args, **options):
        selected = options["category"] or list(PACKS)
        data_dir = Path(__file__).resolve().parents[2] / "catalog_data"
        replace_current = not options["append"]

        with transaction.atomic():
            for slug in selected:
                try:
                    category = Category.objects.get(slug=slug)
                except Category.DoesNotExist as exc:
                    raise CommandError(
                        f"Category '{slug}' does not exist. Seed the marketplace domain first."
                    ) from exc

                csv_path = data_dir / PACKS[slug]
                if not csv_path.exists():
                    raise CommandError(f"Missing catalog file: {csv_path}")

                result = import_category_catalog(
                    category=category,
                    csv_text=csv_path.read_text(encoding="utf-8"),
                    replace_current=replace_current,
                )
                category.refresh_from_db(fields=("schema_version",))

                self.stdout.write(
                    self.style.SUCCESS(
                        f"{slug}: {result.rows} rows, "
                        f"{result.fields_created} fields created, "
                        f"{result.fields_updated} fields updated, "
                        f"{result.options_created} options created, "
                        f"{result.options_updated} options updated, "
                        f"{result.options_deactivated} options deactivated, "
                        f"{result.dependencies_created} dependency links, "
                        f"schema v{category.schema_version}"
                    )
                )

            if options["dry_run"]:
                transaction.set_rollback(True)
                self.stdout.write(
                    self.style.WARNING(
                        "Dry run complete. All database changes were rolled back."
                    )
                )
