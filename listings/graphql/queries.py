import base64
from uuid import UUID
import strawberry
from listings.models import Listing, RecentlyViewedListing
from listings.search import apply_listing_filters, apply_listing_sort
from marketlift.graphql.auth import require_seller, require_user
from promotions.models import ListingPromotion, PromotionProduct
from django.utils import timezone
from .inputs import ListingFilterInput
from .mappers import listing_queryset, listing_to_type
from .types import ListingConnectionType, ListingPageInfoType, ListingType


def _looks_like_uuid(value):
    try:
        UUID(value)
        return True
    except (ValueError, TypeError):
        return False


def _encode_cursor(offset):
    return base64.urlsafe_b64encode(f"offset:{offset}".encode()).decode().rstrip("=")


def _decode_cursor(value):
    if not value:
        return 0
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        prefix, n = raw.split(":", 1)
        return max(0, int(n)) if prefix == "offset" else 0
    except Exception:
        return 0


def _filtered(filters):
    filters = filters or ListingFilterInput()
    qs = listing_queryset(Listing.objects.public())
    qs = apply_listing_filters(qs, filters)
    return apply_listing_sort(qs, filters.sort)


@strawberry.type
class ListingQuery:
    @strawberry.field
    def listings(
        self,
        filters: ListingFilterInput | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ListingType]:
        qs = _filtered(filters)
        start = max(0, offset)
        return [listing_to_type(x) for x in qs[start : start + max(1, min(limit, 100))]]

    @strawberry.field
    def listing_search(
        self,
        filters: ListingFilterInput | None = None,
        first: int = 24,
        after: str | None = None,
    ) -> ListingConnectionType:
        first = max(1, min(first, 100))
        offset = _decode_cursor(after)
        qs = _filtered(filters)
        total = qs.count()
        rows = list(qs[offset : offset + first + 1])
        has_next = len(rows) > first
        rows = rows[:first]
        return ListingConnectionType(
            items=[listing_to_type(x) for x in rows],
            page_info=ListingPageInfoType(
                has_next_page=has_next,
                end_cursor=_encode_cursor(offset + len(rows)) if rows else None,
            ),
            total_count=total,
        )

    @strawberry.field
    def listing(self, id: str) -> ListingType | None:
        qs = listing_queryset(Listing.objects.public())
        try:
            item = qs.get(pk=id) if _looks_like_uuid(id) else qs.get(slug=id)
        except Listing.DoesNotExist:
            return None
        return listing_to_type(item)

    @strawberry.field
    def featured_listings(self, limit: int = 8) -> list[ListingType]:
        now = timezone.now()
        qs = (
            listing_queryset(Listing.objects.public())
            .filter(
                promotions__product__code=PromotionProduct.Code.FEATURED,
                promotions__cancelled_at__isnull=True,
                promotions__starts_at__lte=now,
                promotions__ends_at__gt=now,
            )
            .distinct()
            .order_by("-promotions__starts_at", "-created_at")
        )
        return [listing_to_type(x) for x in qs[: max(1, min(limit, 50))]]

    @strawberry.field
    def my_listings(self, info: strawberry.Info) -> list[ListingType]:
        seller = require_seller(info)
        return [listing_to_type(x) for x in listing_queryset(seller.listings.all())]

    @strawberry.field
    def my_saved_listings(self, info: strawberry.Info) -> list[ListingType]:
        user = require_user(info)
        return [
            listing_to_type(x)
            for x in listing_queryset(Listing.objects.public()).filter(
                saved_by__user=user
            )
        ]

    @strawberry.field
    def my_recently_viewed_listings(
        self, info: strawberry.Info, limit: int = 20
    ) -> list[ListingType]:
        user = require_user(info)
        ids = list(
            RecentlyViewedListing.objects.filter(user=user).values_list(
                "listing_id", flat=True
            )[: max(1, min(limit, 50))]
        )
        rows = {
            x.id: x
            for x in listing_queryset(Listing.objects.public()).filter(id__in=ids)
        }
        return [listing_to_type(rows[i]) for i in ids if i in rows]
