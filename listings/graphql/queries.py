import base64
from decimal import Decimal
from uuid import UUID
import strawberry
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from listings.models import Listing, RecentlyViewedListing
from listings.search import apply_listing_filters, apply_listing_sort
from marketlift.graphql.auth import require_seller, require_staff, require_user
from marketlift.graphql.errors import validation_error
from marketlift.search import SearchRequest, search_listings
from marketlift.location.validators import validate_coordinates, validate_radius_km
from promotions.models import PromotionProduct
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


def _get_public(value):
    qs = listing_queryset(Listing.objects.public())
    return qs.get(pk=value) if _looks_like_uuid(value) else qs.get(slug=value)


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
        filters = filters or ListingFilterInput()
        try:
            page = search_listings(
                SearchRequest(
                    q=filters.q or "",
                    category=filters.category,
                    country_code=filters.country_code,
                    state=filters.state,
                    city=filters.city,
                    district=filters.district,
                    latitude=filters.latitude,
                    longitude=filters.longitude,
                    radius_km=filters.radius_km,
                    min_price=(
                        Decimal(str(filters.min_price))
                        if filters.min_price is not None
                        else None
                    ),
                    max_price=(
                        Decimal(str(filters.max_price))
                        if filters.max_price is not None
                        else None
                    ),
                    condition=filters.condition,
                    seller_type=filters.seller_type,
                    seller_id=str(filters.seller_id) if filters.seller_id else None,
                    verified_only=filters.verified_only,
                    date_listed=filters.date_listed,
                    attribute_filters=dict(filters.attribute_filters or {}),
                    sort=filters.sort,
                    page_size=max(1, min(first, 50)),
                    cursor=after,
                )
            )
        except ValidationError as exc:
            raise validation_error(exc, code="SEARCH_VALIDATION_ERROR") from exc

        return ListingConnectionType(
            items=[listing_to_type(x) for x in page.items],
            page_info=ListingPageInfoType(
                has_next_page=page.next_cursor is not None,
                end_cursor=page.next_cursor,
            ),
            total_count=page.total_count,
        )

    @strawberry.field
    def listing(self, id: str) -> ListingType | None:
        try:
            return listing_to_type(_get_public(id))
        except Listing.DoesNotExist:
            return None

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
    def recent_listings(self, limit: int = 12) -> list[ListingType]:
        qs = listing_queryset(Listing.objects.public()).order_by(
            "-published_at", "-created_at"
        )
        return [listing_to_type(x) for x in qs[: max(1, min(limit, 50))]]

    @strawberry.field
    def nearby_listings(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 10.0,
        limit: int = 12,
    ) -> list[ListingType]:
        try:
            lat, lng = validate_coordinates(latitude, longitude, required=True)
            radius = validate_radius_km(radius_km)
        except ValidationError as exc:
            raise validation_error(exc, code="SEARCH_VALIDATION_ERROR") from exc
        origin = Point(lng, lat, srid=4326)
        qs = (
            listing_queryset(Listing.objects.public())
            .exclude(location_point__isnull=True)
            .filter(location_point__distance_lte=(origin, D(km=radius)))
            .annotate(distance=Distance("location_point", origin))
            .order_by("distance", "-published_at", "-id")
        )
        rows = list(qs[: max(1, min(limit, 50))])
        for row in rows:
            row.search_distance_km = round(float(row.distance.km), 3)
        return [listing_to_type(x) for x in rows]

    @strawberry.field
    def similar_listings(self, listing_id: str, limit: int = 8) -> list[ListingType]:
        try:
            source = _get_public(listing_id)
        except Listing.DoesNotExist:
            return []
        qs = (
            listing_queryset(Listing.objects.public())
            .filter(category_id=source.category_id)
            .exclude(pk=source.pk)
        )
        qs = qs.order_by("-created_at")
        return [listing_to_type(x) for x in qs[: max(1, min(limit, 50))]]

    @strawberry.field
    def my_listings(self, info: strawberry.Info) -> list[ListingType]:
        seller = require_seller(info)
        return [
            listing_to_type(x)
            for x in listing_queryset(
                seller.listings.filter(seller_deleted_at__isnull=True)
            )
        ]

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

    @strawberry.field
    def admin_listings(
        self,
        info: strawberry.Info,
        search: str | None = None,
        status: str | None = None,
        include_seller_deleted: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ListingType]:
        require_staff(info, roles={"admin", "moderator", "support"})
        qs = Listing.objects.all()
        if not include_seller_deleted:
            qs = qs.filter(seller_deleted_at__isnull=True)
        if status:
            qs = qs.filter(status=status)
        if search:
            qs = qs.filter(
                Q(title__icontains=search)
                | Q(seller__display_name__icontains=search)
                | Q(seller__user__email__icontains=search)
                | Q(category_name_snapshot__icontains=search)
            )
        start = max(0, offset)
        return [
            listing_to_type(x)
            for x in listing_queryset(qs)[start : start + max(1, min(limit, 200))]
        ]

    @strawberry.field
    def admin_listing(self, info: strawberry.Info, id: str) -> ListingType | None:
        require_staff(info, roles={"admin", "moderator", "support"})
        qs = listing_queryset(Listing.objects.all())
        try:
            item = qs.get(pk=id) if _looks_like_uuid(id) else qs.get(slug=id)
        except Listing.DoesNotExist:
            return None
        return listing_to_type(item)
