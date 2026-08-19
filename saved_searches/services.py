from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from listings.search import apply_listing_filters
from listings.models import Listing
from notifications.services import create_notification
from .models import SavedSearch, SavedSearchMatch

ALLOWED_CRITERIA = {
    "q",
    "category",
    "state",
    "city",
    "district",
    "min_price",
    "max_price",
    "condition",
    "seller_type",
    "verified_only",
    "date_listed",
    "attribute_filters",
    "sort",
}
CRITERIA_ALIASES = {
    "minPrice": "min_price",
    "maxPrice": "max_price",
    "sellerType": "seller_type",
    "verifiedOnly": "verified_only",
    "dateListed": "date_listed",
    "attributeFilters": "attribute_filters",
}


def normalize_criteria(criteria):
    source = criteria or {}
    normalized = {CRITERIA_ALIASES.get(k, k): v for k, v in source.items()}
    data = {
        k: v
        for k, v in normalized.items()
        if k in ALLOWED_CRITERIA and v not in (None, "", [], {})
    }
    if len(data) > 20:
        raise ValidationError("Too many saved-search filters.")
    return data


def create_saved_search(*, user, name, criteria, alerts_enabled=True):
    criteria = normalize_criteria(criteria)
    if not criteria:
        raise ValidationError("Save at least one search filter.")
    if user.saved_searches.filter(active=True).count() >= 50:
        raise ValidationError("You can keep up to 50 active saved searches.")
    return SavedSearch.objects.create(
        user=user,
        name=(name or "").strip()[:120],
        criteria=criteria,
        alerts_enabled=alerts_enabled,
    )


def matching_queryset(saved_search):
    queryset = Listing.objects.public().exclude(seller__user=saved_search.user)
    return apply_listing_filters(queryset, saved_search.criteria)


@transaction.atomic
def process_saved_search(saved_search, *, now=None):
    now = now or timezone.now()
    since = saved_search.last_checked_at or saved_search.created_at
    matches = list(
        matching_queryset(saved_search)
        .filter(created_at__gt=since)
        .order_by("created_at")[:100]
    )
    new = []
    for listing in matches:
        match, created = SavedSearchMatch.objects.get_or_create(
            saved_search=saved_search, listing=listing
        )
        if created:
            new.append((match, listing))
    if new and saved_search.alerts_enabled:
        first = new[0][1]
        count = len(new)
        create_notification(
            user=saved_search.user,
            notification_type="listing",
            title="New listings match your saved search",
            body=(
                first.title
                if count == 1
                else f"{count} new listings match {saved_search.name or 'your saved search'}."
            ),
            href="/search",
            data={
                "savedSearchId": str(saved_search.id),
                "listingIds": [str(x[1].id) for x in new[:10]],
            },
        )
        SavedSearchMatch.objects.filter(pk__in=[x[0].pk for x in new]).update(
            notified_at=now
        )
        saved_search.last_notified_at = now
    saved_search.last_checked_at = now
    saved_search.save(
        update_fields=("last_checked_at", "last_notified_at", "updated_at")
    )
    return len(new)
