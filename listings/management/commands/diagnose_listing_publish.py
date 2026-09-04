from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from listings.models import Listing
from listings.services import publish_listing


class Command(BaseCommand):
    help = "Diagnose why a listing cannot be published without changing its status."

    def add_arguments(self, parser):
        parser.add_argument("--listing")
        parser.add_argument(
            "--latest",
            action="store_true",
            help="Diagnose the newest non-deleted seller listing.",
        )

    def handle(self, *args, **options):
        listing_id = (options.get("listing") or "").strip()
        qs = Listing.objects.filter(
            seller_deleted_at__isnull=True
        ).select_related(
            "category", "seller"
        ).prefetch_related(
            "media", "attribute_values"
        )

        listing = (
            qs.filter(pk=listing_id).first()
            if listing_id
            else qs.order_by("-created_at").first()
        )

        if listing is None:
            raise CommandError("No listing found to diagnose.")

        self.stdout.write(f"Listing: {listing.id}")
        self.stdout.write(f"Status: {listing.status}")
        self.stdout.write(
            f"Category: {listing.category.slug if listing.category else '(none)'}"
        )
        self.stdout.write(f"Condition: {listing.condition or '(blank)'}")
        self.stdout.write(f"Images: {listing.media.count()}")
        self.stdout.write(
            "Attributes: "
            + ", ".join(
                sorted(item.key for item in listing.attribute_values.all())
            )
        )

        with transaction.atomic():
            try:
                publish_listing(listing)
            except ValidationError as exc:
                if hasattr(exc, "message_dict"):
                    self.stderr.write(self.style.ERROR(str(exc.message_dict)))
                else:
                    self.stderr.write(
                        self.style.ERROR("; ".join(exc.messages))
                    )
                transaction.set_rollback(True)
                return

            transaction.set_rollback(True)
            self.stdout.write(
                self.style.SUCCESS(
                    "Publish validation passed. Transaction was rolled back; "
                    "the listing was not changed."
                )
            )
