from decimal import Decimal
from django.utils import timezone
from marketlift.graphql.types import LocationType
from promotions.models import PromotionProduct
from sellers.graphql.mappers import seller_to_type
from listings.querysets import with_listing_card_data
from .types import ListingType


def active_promotion_codes(listing) -> set[str]:
    now = timezone.now()
    if (
        hasattr(listing, "_prefetched_objects_cache")
        and "promotions" in listing._prefetched_objects_cache
    ):
        return {
            p.product.code
            for p in listing.promotions.all()
            if p.cancelled_at is None and p.starts_at <= now < p.ends_at
        }
    return set(
        listing.promotions.filter(
            cancelled_at__isnull=True, starts_at__lte=now, ends_at__gt=now
        ).values_list("product__code", flat=True)
    )


def listing_queryset(queryset=None):
    from listings.models import Listing

    qs = queryset if queryset is not None else Listing.objects.all()
    return with_listing_card_data(qs)


def listing_to_type(listing) -> ListingType:
    attrs = {}
    for item in listing.attribute_values.all():
        value = item.value
        attrs[item.key] = float(value) if isinstance(value, Decimal) else value
    codes = active_promotion_codes(listing)
    return ListingType(
        id=str(listing.id),
        slug=listing.slug,
        title=listing.title,
        description=listing.description,
        price=float(listing.price) if listing.price is not None else None,
        category=listing.category_slug,
        category_name=listing.category_name,
        category_schema_version=listing.category_schema_version,
        condition=listing.condition or None,
        location=LocationType(
            state=listing.state,
            state_code=listing.state_code,
            city=listing.city,
            district=listing.district or None,
        ),
        images=[m.content_url for m in listing.media.all()],
        seller=seller_to_type(listing.seller),
        created_at=listing.created_at,
        expires_at=listing.expires_at,
        status=listing.status,
        views=listing.views,
        negotiable=listing.negotiable,
        attributes=attrs,
        featured=PromotionProduct.Code.FEATURED in codes,
        urgent=PromotionProduct.Code.URGENT in codes,
        favorites=int(getattr(listing, "favorite_count", 0)),
        inquiries=int(getattr(listing, "inquiry_count", 0)),
        seller_deleted_at=listing.seller_deleted_at,
    )
