
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from categories.catalogs import import_category_catalog
from categories.models import Category


PACKS = {
    "phones": {"file": "phones.csv", "target": "phones", "fallback": "phones"},
    "computers": {"file": "computers.csv", "target": "computers", "fallback": "computers"},
    "vehicles": {"file": "vehicles.csv", "target": "cars", "fallback": "vehicles"},
    "electronics": {"file": "electronics.csv", "target": "other-electronics", "fallback": "electronics"},
    "printers-scanners": {"file": "printers-scanners.csv", "target": "printers-scanners", "fallback": "printers-scanners"},
    "networking": {"file": "networking.csv", "target": "networking", "fallback": "networking"},
    "gaming": {"file": "gaming.csv", "target": "gaming", "fallback": "gaming"},
    "cameras": {"file": "cameras.csv", "target": "cameras", "fallback": "cameras"},
    "audio": {"file": "audio.csv", "target": "audio", "fallback": "audio"},
    "tvs-video": {"file": "tvs-video.csv", "target": "tvs-video", "fallback": "tvs-video"},
    "smart-watches": {"file": "smart-watches.csv", "target": "smart-watches", "fallback": "smart-watches"},
    "tablets": {"file": "tablets.csv", "target": "tablets", "fallback": "tablets"},
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

    def _resolve_category(self, pack_name: str):
        spec = PACKS[pack_name]
        category = Category.objects.filter(slug=spec["target"]).first()
        if category is None:
            category = Category.objects.filter(slug=spec["fallback"]).first()
        if category is None:
            raise CommandError(
                f"Neither target category '{spec['target']}' nor fallback "
                f"'{spec['fallback']}' exists for catalog '{pack_name}'."
            )
        return category

    def _verify_catalog(self, *, category, csv_path):
        import csv

        from categories.models import CategoryField, CategoryFieldOptionDependency

        with csv_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))

        definitions = {}
        expected_options = {}
        expected_links = set()

        for row in rows:
            key = row["field_key"].strip()
            definitions.setdefault(
                key,
                {
                    "depends_on": row.get("depends_on", "").strip(),
                    "allow_custom": row.get("allow_custom", "").strip().lower()
                    in {"1", "true", "yes", "y", "on"},
                    "lazy": row.get("lazy", "").strip().lower()
                    in {"1", "true", "yes", "y", "on"},
                },
            )
            expected_options.setdefault(key, set()).add(
                row["option_value"].strip() or row["option_label"].strip()
            )
            parent = row.get("parent_value", "").strip()
            depends_on = row.get("depends_on", "").strip()
            if depends_on and parent:
                expected_links.add(
                    (
                        key,
                        row["option_value"].strip() or row["option_label"].strip(),
                        depends_on,
                        parent,
                    )
                )

        fields = {
            item.key: item
            for item in CategoryField.objects.select_related("depends_on").filter(
                category=category,
                key__in=definitions,
            )
        }

        problems = []
        for key, definition in definitions.items():
            field = fields.get(key)
            if field is None:
                problems.append(f"{key}: field missing")
                continue

            if field.field_type != CategoryField.FieldType.SELECT:
                problems.append(f"{key}: expected select, got {field.field_type}")

            expected_parent = definition["depends_on"] or None
            actual_parent = field.depends_on.key if field.depends_on_id else None
            if actual_parent != expected_parent:
                problems.append(
                    f"{key}: expected parent {expected_parent!r}, got {actual_parent!r}"
                )

            if field.lazy_options != definition["lazy"]:
                problems.append(
                    f"{key}: lazy_options={field.lazy_options}, expected {definition['lazy']}"
                )

            if field.allow_custom_value != definition["allow_custom"]:
                problems.append(
                    f"{key}: allow_custom_value={field.allow_custom_value}, "
                    f"expected {definition['allow_custom']}"
                )

            active_values = set(
                field.options.filter(active=True).values_list("value", flat=True)
            )
            missing = expected_options[key] - active_values
            if missing:
                sample = ", ".join(sorted(missing)[:5])
                problems.append(
                    f"{key}: {len(missing)} expected active options missing "
                    f"(e.g. {sample})"
                )

        for child_key, child_value, parent_key, parent_value in expected_links:
            child_field = fields.get(child_key)
            parent_field = fields.get(parent_key)
            if child_field is None or parent_field is None:
                continue
            child_option = child_field.options.filter(
                value=child_value,
                active=True,
            ).first()
            parent_option = parent_field.options.filter(
                value=parent_value,
                active=True,
            ).first()
            if child_option is None or parent_option is None:
                continue
            if not CategoryFieldOptionDependency.objects.filter(
                option=child_option,
                parent_option=parent_option,
            ).exists():
                problems.append(
                    f"missing dependency: {parent_key}={parent_value} -> "
                    f"{child_key}={child_value}"
                )
                if len(problems) >= 20:
                    break

        if problems:
            raise CommandError(
                "Catalog verification failed for "
                f"{category.slug}:\n- " + "\n- ".join(problems[:20])
            )

    def handle(self, *args, **options):
        selected = options["category"] or list(PACKS)
        data_dir = Path(__file__).resolve().parents[2] / "catalog_data"
        replace_current = not options["append"]

        with transaction.atomic():
            for slug in selected:
                category = self._resolve_category(slug)
                csv_path = data_dir / PACKS[slug]["file"]
                if not csv_path.exists():
                    raise CommandError(f"Missing catalog file: {csv_path}")

                result = import_category_catalog(
                    category=category,
                    csv_text=csv_path.read_text(encoding="utf-8"),
                    replace_current=replace_current,
                )
                category.refresh_from_db(fields=("schema_version",))
                self._verify_catalog(category=category, csv_path=csv_path)

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
