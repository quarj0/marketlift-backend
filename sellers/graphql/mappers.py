from marketlift.graphql.types import LocationType
from .types import AdminSellerType, SellerType


def seller_to_type(seller) -> SellerType:
    user = seller.user
    return SellerType(
        id=str(seller.id),
        name=seller.display_name or user.full_name or user.email,
        verified=seller.verified,
        seller_type=seller.seller_type,
        is_suspended=seller.is_suspended,
        location=LocationType(
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
        verified=seller.verified,
        suspended=seller.is_suspended,
        activated_at=seller.activated_at,
        suspended_at=seller.suspended_at,
        suspension_reason=seller.suspension_reason or None,
        listing_count=seller.listings.count(),
    )
