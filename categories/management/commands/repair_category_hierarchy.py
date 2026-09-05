import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from categories.models import Category


class Command(BaseCommand):
    help = (
        "Restore taxonomy-managed parent relationships without changing category "
        "names, images, visibility, fields, or listing assignments."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        path = Path(__file__).resolve().parents[2] / "data" / "taxonomy_v2.json"
        taxonomy = json.loads(path.read_text(encoding="utf-8"))
        expected_parents = {item["slug"]: None for item in taxonomy["roots"]}
        expected_parents.update(
            {item["slug"]: item["parent"] for item in taxonomy["categories"]}
        )

        with transaction.atomic():
            categories = {
                item.slug: item
                for item in Category.objects.select_for_update().filter(
                    slug__in=expected_parents
                )
            }
            missing_parents = sorted(
                {
                    parent_slug
                    for slug, parent_slug in expected_parents.items()
                    if slug in categories
                    and parent_slug is not None
                    and parent_slug not in categories
                }
            )
            if missing_parents:
                raise CommandError(
                    "Cannot repair hierarchy because parent categories are missing: "
                    + ", ".join(missing_parents)
                )

            repaired = []
            for slug, expected_parent_slug in expected_parents.items():
                category = categories.get(slug)
                if category is None:
                    continue
                expected_parent_id = (
                    categories[expected_parent_slug].pk
                    if expected_parent_slug is not None
                    else None
                )
                if category.parent_id == expected_parent_id:
                    continue
                category.parent_id = expected_parent_id
                category.save(update_fields=("parent", "updated_at"))
                repaired.append(slug)

            self.stdout.write(
                self.style.SUCCESS(
                    f"Category hierarchy: {len(repaired)} relationships repaired."
                )
            )
            if repaired:
                self.stdout.write("Repaired: " + ", ".join(sorted(repaired)))
            if options["dry_run"]:
                transaction.set_rollback(True)
                self.stdout.write(
                    self.style.WARNING("Dry run complete; changes rolled back.")
                )
