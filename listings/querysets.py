from __future__ import annotations

from django.db.models import Count


def with_listing_card_data(queryset):
    """Shared eager-loading/aggregates for marketplace listing cards."""
    return (
        queryset.select_related("seller__user", "category")
        .annotate(
            favorite_count=Count("saved_by", distinct=True),
            inquiry_count=Count("conversations", distinct=True),
        )
        .prefetch_related(
            "media__upload__variants",
            "attribute_values",
            "promotions__product",
        )
    )
