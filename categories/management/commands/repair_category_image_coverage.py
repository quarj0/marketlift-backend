from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from categories.models import Category


LEGACY_ROOT_SLUGS = {
    "properties",
    "land",
    "home",
    "agriculture",
    "business",
    "other",
}


class Command(BaseCommand):
    help = (
        "Remove legacy root categories from the active taxonomy and guarantee "
        "that active descendants have a real category image by inheriting the "
        "nearest ancestor image until an explicit child image is uploaded."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--audit-only",
            action="store_true",
            help="Report coverage without changing categories.",
        )
        parser.add_argument(
            "--keep-legacy",
            action="store_true",
            help="Do not hide known pre-taxonomy-v2 legacy roots.",
        )

    def handle(self, *args, **options):
        audit_only = options["audit_only"]
        keep_legacy = options["keep_legacy"]

        with transaction.atomic():
            if not keep_legacy:
                legacy_qs = Category.objects.filter(
                    slug__in=LEGACY_ROOT_SLUGS,
                    parent__isnull=True,
                    active=True,
                )
                legacy = list(legacy_qs.values_list("slug", flat=True))
                if legacy and not audit_only:
                    legacy_qs.update(active=False)
                if legacy:
                    verb = "would hide" if audit_only else "hid"
                    self.stdout.write(
                        self.style.WARNING(
                            f"{verb} {len(legacy)} legacy roots: "
                            + ", ".join(sorted(legacy))
                        )
                    )

            categories = list(
                Category.objects.select_related("parent", "image_upload")
                .filter(active=True)
                .order_by("sort_order", "name")
            )
            by_id = {category.id: category for category in categories}

            inherited = []
            missing = []

            for category in categories:
                if category.image_upload_id:
                    continue

                ancestor = category.parent
                seen = set()
                while ancestor is not None and ancestor.id not in seen:
                    seen.add(ancestor.id)
                    ancestor = by_id.get(ancestor.id, ancestor)

                    if ancestor.image_upload_id:
                        if not audit_only:
                            category.image_upload_id = ancestor.image_upload_id
                            category.save(
                                update_fields=("image_upload", "updated_at")
                            )
                            by_id[category.id] = category

                        inherited.append((category.slug, ancestor.slug))
                        break

                    ancestor = ancestor.parent
                else:
                    missing.append(category.slug)

            total_active = len(categories)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Active category image coverage: {total_active} categories; "
                    f"{len(inherited)} "
                    f"{'would inherit' if audit_only else 'inherited'}; "
                    f"{len(missing)} still missing."
                )
            )

            if inherited:
                sample = ", ".join(
                    f"{child} <- {parent}"
                    for child, parent in inherited[:12]
                )
                self.stdout.write(f"Sample inheritance: {sample}")

            if missing:
                self.stdout.write(
                    self.style.WARNING(
                        "Categories with no image and no imaged ancestor: "
                        + ", ".join(sorted(missing))
                    )
                )

            if audit_only:
                transaction.set_rollback(True)
