from __future__ import annotations

from django.core.management.base import BaseCommand

from listings.models import Listing
from marketlift.search.document import rebuild_listing_search_document


class Command(BaseCommand):
    help = "Rebuild denormalized marketplace listing search documents and vectors."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=500)

    def handle(self, *args, **options):
        batch_size = max(1, min(int(options["batch_size"]), 5000))
        total = Listing.objects.count()
        done = 0
        for listing_id in (
            Listing.objects.order_by("pk")
            .values_list("pk", flat=True)
            .iterator(chunk_size=batch_size)
        ):
            rebuild_listing_search_document(listing_id)
            done += 1
            if done % batch_size == 0:
                self.stdout.write(f"Rebuilt {done}/{total} listing search documents...")
        self.stdout.write(
            self.style.SUCCESS(f"Rebuilt {done} listing search documents.")
        )
