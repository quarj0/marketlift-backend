from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import strawberry
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from listings.models import Listing
from marketlift.graphql.auth import require_seller, require_user
from promotions.models import ListingPromotion, PromotionProduct
from .inputs import ListingFilterInput
from .mappers import listing_queryset, listing_to_type
from .types import ListingType


def _decimal(value):
    return None if value is None else Decimal(str(value))


def _looks_like_uuid(value: str):
    try:
        UUID(value)
        return True
    except ValueError:
        return False


@strawberry.type
class ListingQuery:
    @strawberry.field
    def listings(
        self,
        filters: ListingFilterInput | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ListingType]:
        filters = filters or ListingFilterInput()
        qs = listing_queryset(Listing.objects.public())
        if filters.q:
            qs = qs.filter(
                Q(title__icontains=filters.q) | Q(description__icontains=filters.q)
            )
        if filters.category:
            qs = qs.filter(category__slug=filters.category)
        if filters.state:
            qs = qs.filter(state_code__iexact=filters.state)
        if filters.city:
            qs = qs.filter(city__iexact=filters.city)
        if filters.district:
            qs = qs.filter(district__icontains=filters.district)
        if filters.condition:
            qs = qs.filter(condition=filters.condition)
        if filters.seller_type:
            qs = qs.filter(seller__seller_type=filters.seller_type)
        if filters.verified_only:
            qs = qs.filter(seller__verified_at__isnull=False)
        if filters.min_price is not None:
            qs = qs.filter(price__gte=_decimal(filters.min_price))
        if filters.max_price is not None:
            qs = qs.filter(price__lte=_decimal(filters.max_price))
        if filters.date_listed:
            days = {"today": 1, "week": 7, "month": 30}.get(filters.date_listed)
            if days:
                qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=days))
        if filters.sort == "price_asc":
            qs = qs.order_by("price", "-created_at")
        elif filters.sort == "price_desc":
            qs = qs.order_by("-price", "-created_at")
        elif filters.sort == "newest":
            qs = qs.order_by("-created_at")
        else:
            now = timezone.now()
            featured = ListingPromotion.objects.filter(
                listing_id=OuterRef("pk"),
                product__code=PromotionProduct.Code.FEATURED,
                cancelled_at__isnull=True,
                starts_at__lte=now,
                ends_at__gt=now,
            )
            qs = qs.annotate(is_featured=Exists(featured)).order_by(
                "-is_featured", "-views", "-created_at"
            )
        start = max(0, offset)
        end = start + max(1, min(limit, 100))
        return [listing_to_type(x) for x in qs[start:end]]

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
