from django.core.exceptions import ObjectDoesNotExist

from marketlift.graphql.types import LocationType
from .types import AdminSellerType, SellerType


def seller_to_type(seller) -> SellerType:
    user = seller.user
    total_conversations = int(getattr(seller, "total_conversations", 0) or 0)
    responded_conversations = int(getattr(seller, "responded_conversations", 0) or 0)
    response_rate = (
        round((responded_conversations / total_conversations) * 100, 1)
        if total_conversations
        else None
    )
    try:
        show_phone = seller.settings.show_phone
    except ObjectDoesNotExist:
        # SellerSettings.show_phone defaults to true when the settings row has
        # not been materialized yet. Keep that model default without creating
        # data as a side effect of a public query.
        show_phone = True
    return SellerType(
        id=str(seller.id),
        name=seller.display_name or user.full_name or user.email,
        avatar_url=user.avatar_url or None,
        phone=(user.phone or None) if show_phone else None,
        verified=seller.verified,
        seller_type=seller.seller_type,
        country_code=seller.country_code,
        is_suspended=seller.is_suspended,
        rating=float(seller.rating_average),
        reviews=seller.review_count,
        positive_review_percent=float(seller.positive_review_percent),
        response_rate=response_rate,
        active_listings=int(getattr(seller, "active_listing_count", 0) or 0),
        follower_count=int(getattr(seller, "follower_count", 0) or 0),
        is_followed=bool(getattr(seller, "viewer_follows", False)),
        member_since=seller.activated_at,
        location=LocationType(
            country_code=user.country_code,
            state=user.state,
            state_code=user.state_code,
            city=user.city,
            district=user.district or None,
        ),
    )


def admin_seller_to_type(seller) -> AdminSellerType:
    return AdminSellerType(
        id=str(seller.id),
        user_id=str(seller.user_id),
        name=seller.display_name or seller.user.full_name or seller.user.email,
        email=seller.user.email,
        seller_type=seller.seller_type,
        country_code=seller.country_code,
        verified=seller.verified,
        suspended=seller.is_suspended,
        activated_at=seller.activated_at,
        suspended_at=seller.suspended_at,
        suspension_reason=seller.suspension_reason or None,
        listing_count=int(
            seller.listing_count
            if hasattr(seller, "listing_count")
            else seller.listings.count()
        ),
    )
