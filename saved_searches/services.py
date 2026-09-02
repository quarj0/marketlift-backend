from dataclasses import replace
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from marketlift.search import SearchRequest, search_listings
from marketlift.search.parser import parse_marketplace_query
from marketlift.search.service import validate_search_request
from notifications.services import create_notification

from .models import SavedSearch, SavedSearchMatch

ALLOWED_CRITERIA = {
    "q",
    "category",
    "country_code",
    "state",
    "city",
    "district",
    "latitude",
    "longitude",
    "radius_km",
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
    "countryCode": "country_code",
    "radiusKm": "radius_km",
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


def _decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError("Saved-search price must be numeric.") from exc


def _request_from_criteria(
    criteria,
    *,
    page_size=50,
    cursor=None,
    exclude_user_id=None,
    created_after=None,
    allow_relaxation=False,
):
    criteria = criteria or {}
    return SearchRequest(
        q=str(criteria.get("q") or ""),
        category=criteria.get("category"),
        country_code=criteria.get("country_code"),
        state=criteria.get("state"),
        city=criteria.get("city"),
        district=criteria.get("district"),
        latitude=criteria.get("latitude"),
        longitude=criteria.get("longitude"),
        radius_km=criteria.get("radius_km"),
        min_price=_decimal(criteria.get("min_price")),
        max_price=_decimal(criteria.get("max_price")),
        condition=criteria.get("condition"),
        seller_type=criteria.get("seller_type"),
        verified_only=(
            criteria.get("verified_only", False)
            if isinstance(criteria.get("verified_only", False), bool)
            else str(criteria.get("verified_only", "")).strip().casefold()
            in {"true", "1"}
        ),
        date_listed=criteria.get("date_listed"),
        attribute_filters=dict(criteria.get("attribute_filters") or {}),
        sort="newest",
        page_size=page_size,
        cursor=cursor,
        exclude_user_id=str(exclude_user_id) if exclude_user_id else None,
        created_after=created_after,
        allow_relaxation=allow_relaxation,
    )


def _validate_saved_criteria(criteria):
    request = _request_from_criteria(criteria, page_size=1)
    validate_search_request(request)
    parse_marketplace_query(request.q)


def create_saved_search(*, user, name, criteria, alerts_enabled=True):
    criteria = normalize_criteria(criteria)
    if not criteria:
        raise ValidationError("Save at least one search filter.")
    _validate_saved_criteria(criteria)

    existing = user.saved_searches.filter(active=True, criteria=criteria).first()
    if existing is not None:
        changed = []
        if alerts_enabled and not existing.alerts_enabled:
            existing.alerts_enabled = True
            changed.append("alerts_enabled")
        next_name = (name or "").strip()[:120]
        if next_name and next_name != existing.name:
            existing.name = next_name
            changed.append("name")
        if changed:
            changed.append("updated_at")
            existing.save(update_fields=tuple(changed))
        return existing

    if user.saved_searches.filter(active=True).count() >= 50:
        raise ValidationError("You can keep up to 50 active saved searches.")
    return SavedSearch.objects.create(
        user=user,
        name=(name or "").strip()[:120],
        criteria=criteria,
        alerts_enabled=alerts_enabled,
    )


def matching_listings(saved_search, *, since=None, limit=100):
    """Use the same search engine as the marketplace, without UI relaxation.

    Saved alerts are strict: an `8gb` saved search should not notify about a 6GB
    listing merely because the interactive search UI can show relaxed fallbacks.
    """
    limit = max(1, min(int(limit), 100))
    page_size = min(50, limit)
    request = _request_from_criteria(
        saved_search.criteria,
        page_size=page_size,
        exclude_user_id=saved_search.user_id,
        created_after=since,
        allow_relaxation=False,
    )
    rows = []
    while len(rows) < limit:
        page = search_listings(request)
        rows.extend(page.items)
        if not page.next_cursor or len(rows) >= limit:
            break
        request = replace(request, cursor=page.next_cursor)
    return rows[:limit]


@transaction.atomic
def process_saved_search(saved_search, *, now=None):
    now = now or timezone.now()
    since = saved_search.last_checked_at or saved_search.created_at
    matches = matching_listings(saved_search, since=since, limit=100)
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
