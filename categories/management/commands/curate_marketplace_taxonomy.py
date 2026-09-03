
import json
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from categories.models import Category, CategoryField, CategoryFieldOption
from listings.models import Listing
from marketlift.search.document import rebuild_listing_search_document


SOURCE_SCHEMA_MOVES = {
    "phones-tablets": "other-phones-tablets",
    "vehicles": "cars",
    "electronics": "other-electronics",
    "property": "other-property",
    "home-furniture-appliances": "other-home-furniture-appliances",
    "fashion": "other-fashion",
    "beauty-personal-care": "other-beauty-personal-care",
    "babies-kids": "other-babies-kids",
    "animals-pets": "other-pets",
    "food-agriculture-farming": "other-food-agriculture-farming",
    "jobs": "other-jobs",
    "services": "other-services",
    "repair-construction": "other-repair-construction",
    "leisure-activities": "other-leisure-activities",
    "business-industry": "other-business-industry",
    "commercial-equipments-tools": "other-commercial-equipment",
}


class Command(BaseCommand):
    help = "Curate Marketlift's production categories into taxonomy v2."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--force-field-metadata",
            action="store_true",
            help="Refresh existing leaf field metadata only when no historical values use that field.",
        )

    def handle(self, *args, **options):
        path = Path(__file__).resolve().parents[2] / "data" / "taxonomy_v2.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        affected_listing_ids = []

        with transaction.atomic():
            category_map = {}

            for item in data["roots"]:
                category, _ = Category.objects.get_or_create(
                    slug=item["slug"],
                    defaults={
                        "name": item["name"],
                        "icon": item["icon"],
                        "active": True,
                        "sort_order": item["sort"],
                    },
                )
                category.name = item["name"]
                category.icon = item["icon"]
                category.parent = None
                category.active = True
                category.sort_order = item["sort"]
                category.save(
                    update_fields=(
                        "name",
                        "icon",
                        "parent",
                        "active",
                        "sort_order",
                        "updated_at",
                    )
                )
                category_map[category.slug] = category

            pending = list(data["categories"])
            while pending:
                progressed = False
                for item in list(pending):
                    parent = category_map.get(item["parent"])
                    if parent is None:
                        continue
                    category, _ = Category.objects.get_or_create(
                        slug=item["slug"],
                        defaults={
                            "name": item["name"],
                            "icon": item["icon"],
                            "parent": parent,
                            "active": True,
                            "sort_order": item["sort"],
                        },
                    )
                    category.name = item["name"]
                    category.icon = item["icon"]
                    category.parent = parent
                    category.active = True
                    category.sort_order = item["sort"]
                    category.save(
                        update_fields=(
                            "name",
                            "icon",
                            "parent",
                            "active",
                            "sort_order",
                            "updated_at",
                        )
                    )
                    category_map[category.slug] = category
                    pending.remove(item)
                    progressed = True

                if not progressed:
                    unresolved = ", ".join(item["slug"] for item in pending)
                    raise RuntimeError(f"Unresolved taxonomy parents: {unresolved}")

            # Reparent existing production categories that previously appeared as duplicates.
            for slug, parent_slug, name in (
                ("phones-tablets", "electronics", "Phones & Tablets"),
                ("computers", "electronics", "Computers"),
                ("commercial-equipments-tools", "business-industry", "Commercial Equipment & Tools"),
            ):
                category = Category.objects.filter(slug=slug).first()
                if category:
                    category.parent = category_map[parent_slug]
                    category.name = name
                    category.active = True
                    category.save(update_fields=("parent", "name", "active", "updated_at"))
                    category_map[slug] = category

            # Move the existing generic/root schema to its curated fallback leaf.
            # The exact same CategoryField rows are moved, so ListingAttribute.field
            # references and field snapshots remain valid.
            for source_slug, target_slug in SOURCE_SCHEMA_MOVES.items():
                source = Category.objects.filter(slug=source_slug).first()
                target = category_map.get(target_slug)
                if source is None or target is None:
                    continue

                if source.fields.exists() and not target.fields.exists():
                    source_version = source.schema_version
                    source.fields.update(category=target)
                    target.schema_version = max(target.schema_version, source_version)
                    target.save(update_fields=("schema_version", "updated_at"))

                qs = Listing.objects.filter(category=source)
                ids = list(qs.values_list("id", flat=True))
                if ids:
                    qs.update(
                        category=target,
                        category_slug_snapshot=target.slug,
                        category_name_snapshot=target.name,
                        category_schema_version=target.schema_version,
                    )
                    affected_listing_ids.extend(ids)

            # Seed missing fields on new leaves. Existing fields are preserved.
            for item in data["categories"]:
                category = category_map[item["slug"]]
                for index, spec in enumerate(item.get("fields", [])):
                    self._ensure_field(
                        category=category,
                        spec=spec,
                        sort_order=index,
                        force=options["force_field_metadata"],
                    )

            self.stdout.write(
                self.style.SUCCESS(
                    f"Taxonomy v2: {len(data['roots'])} root categories, "
                    f"{len(data['categories'])} descendants, "
                    f"{len(affected_listing_ids)} listings reassigned."
                )
            )

            if options["dry_run"]:
                transaction.set_rollback(True)
                self.stdout.write(
                    self.style.WARNING("Dry run complete. All taxonomy changes rolled back.")
                )
                return

        for listing_id in affected_listing_ids:
            rebuild_listing_search_document(listing_id)

    def _ensure_field(self, *, category, spec, sort_order, force):
        defaults = {
            "label": spec["label"],
            "field_type": spec["type"],
            "required": spec.get("required", False),
            "filterable": spec.get("filterable", True),
            "allow_custom_value": spec.get("allow_custom", False),
            "placeholder": spec.get("placeholder", ""),
            "unit": spec.get("unit", ""),
            "min_value": self._decimal(spec.get("min")),
            "max_value": self._decimal(spec.get("max")),
            "sort_order": sort_order,
        }

        field, created = CategoryField.objects.get_or_create(
            category=category,
            key=spec["key"],
            defaults=defaults,
        )

        if force and not created and not field.listing_values.exists():
            for key, value in defaults.items():
                setattr(field, key, value)
            field.save()

        for option_index, option in enumerate(spec.get("options", [])):
            CategoryFieldOption.objects.update_or_create(
                field=field,
                value=option["value"],
                defaults={
                    "label": option["label"],
                    "active": True,
                    "sort_order": option_index,
                },
            )

    @staticmethod
    def _decimal(value):
        return None if value is None else Decimal(str(value))
