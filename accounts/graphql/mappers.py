from .types import AccountType, AdminUserType, SellerCapabilityType


def account_to_type(user) -> AccountType:
    seller = getattr(user, "seller_profile", None)
    seller_type = None
    if seller is not None:
        seller_type = SellerCapabilityType(
            seller_id=str(seller.id),
            activated_at=seller.activated_at,
            verified=seller.verified,
            suspended=seller.is_suspended,
        )
    return AccountType(
        id=str(user.id),
        name=user.full_name or user.email,
        email=user.email,
        phone=user.phone,
        avatar_url=user.avatar_url or None,
        bio=user.bio or None,
        state=user.state,
        state_code=user.state_code,
        city=user.city,
        district=user.district or None,
        email_verified=user.email_verified_at is not None,
        phone_verified=user.phone_verified_at is not None,
        active=user.is_active,
        staff=user.is_staff,
        seller_profile=seller_type,
    )


def admin_user_to_type(user) -> AdminUserType:
    return AdminUserType(
        id=str(user.id),
        name=user.full_name or user.email,
        email=user.email,
        phone=user.phone,
        active=user.is_active,
        staff=user.is_staff,
        seller_enabled=hasattr(user, "seller_profile"),
        created_at=user.date_joined,
        suspended_at=user.suspended_at,
        suspension_reason=user.suspension_reason or None,
    )
