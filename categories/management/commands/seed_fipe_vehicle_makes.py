from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from categories.dynamic_catalogs import fipe
from categories.dynamic_catalogs.service import _prune_root, _upsert_root_option
from categories.models import Category, CategoryField


class Command(BaseCommand):
    help = (
        "Seed only the bundled FIPE vehicle makes. "
        "This command does not fetch or create models and years."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--category",
            action="append",
            choices=sorted(fipe.VEHICLE_SCOPES),
            help="Category slug to seed. Repeat as needed; defaults to all vehicles.",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        selected = options["category"] or list(fipe.VEHICLE_SCOPES)

        with transaction.atomic():
            for slug in selected:
                try:
                    category = Category.objects.get(slug=slug)
                    field = category.fields.get(key="make")
                except Category.DoesNotExist as exc:
                    raise CommandError(f"Category '{slug}' does not exist.") from exc
                except CategoryField.DoesNotExist as exc:
                    raise CommandError(
                        f"Category '{slug}' does not have a make field."
                    ) from exc

                scope = fipe.VEHICLE_SCOPES[slug]
                makes = fipe.brands(scope)
                if not makes:
                    raise CommandError(
                        f"The bundled FIPE make snapshot has no data for '{scope}'."
                    )

                keep_ids = set()
                for sort_order, item in enumerate(makes):
                    name = " ".join(str(item.get("name") or "").split())
                    if not name:
                        continue
                    option = _upsert_root_option(field, name, sort_order)
                    keep_ids.add(option.pk)

                if not keep_ids:
                    raise CommandError(f"No usable makes were found for '{slug}'.")

                _prune_root(field, keep_ids)
                category.schema_version += 1
                category.save(update_fields=("schema_version", "updated_at"))
                self.stdout.write(
                    self.style.SUCCESS(f"{slug}: {len(keep_ids)} makes seeded.")
                )

            if options["dry_run"]:
                transaction.set_rollback(True)
                self.stdout.write(
                    self.style.WARNING("Dry run complete; changes rolled back.")
                )
