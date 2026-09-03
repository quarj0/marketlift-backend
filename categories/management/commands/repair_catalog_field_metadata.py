from decimal import Decimal

from django.core.management.base import BaseCommand

from categories.models import Category


class Command(BaseCommand):
    help = "Normalize selected category field bounds after catalog expansion."

    def handle(self, *args, **options):
        computers = Category.objects.filter(slug="computers").first()
        if computers:
            changed = computers.fields.filter(key="screen_size").update(
                min_value=Decimal("10"),
                max_value=Decimal("60"),
            )
            if changed:
                computers.schema_version += 1
                computers.save(update_fields=("schema_version", "updated_at"))
                self.stdout.write(
                    self.style.SUCCESS(
                        "computers.screen_size normalized to 10–60 inches."
                    )
                )
