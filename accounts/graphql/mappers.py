from marketlift.graphql.types import LocationType
from .types import (
    AccountSettingsType,
    AccountUserType,
    AdminUserType,
    SellerCapabilityType,
)


def user_to_type(user):
    seller = getattr(user, "seller_profile", None)
    return AccountUserType(
        id=str(user.id),
        name=user.full_name or user.email,
        email=user.email,
        phone=user.phone,
        avatar_url=user.avatar_url or None,
        bio=user.bio or None,
        location=LocationType(
            state=user.state,
            state_code=user.state_code,
            city=user.city,
            district=user.district or None,
        ),
        email_verified=bool(user.email_verified_at),
        phone_verified=bool(user.phone_verified_at),
        member_since=user.date_joined,
        active=user.is_active,
        staff=user.is_staff,
        seller_profile=(
            SellerCapabilityType(
                seller_id=str(seller.id),
                activated_at=seller.activated_at,
                verified=seller.verified,
                suspended=seller.is_suspended,
            )
            if seller
            else None
        ),
    )


def settings_to_type(x):
    return AccountSettingsType(
        language=x.language,
        currency=x.currency,
        email_messages=x.email_messages,
        email_listing_updates=x.email_listing_updates,
        email_recommendations=x.email_recommendations,
        push_messages=x.push_messages,
        push_listing_updates=x.push_listing_updates,
        marketing_emails=x.marketing_emails,
        show_phone_to_sellers=x.show_phone_to_sellers,
        show_online_status=x.show_online_status,
    )


def admin_user_to_type(user):
    seller = getattr(user, "seller_profile", None)
    return AdminUserType(
        id=str(user.id),
        name=user.full_name or user.email,
        email=user.email,
        phone=user.phone,
        active=user.is_active,
        staff=user.is_staff,
        suspended=bool(user.suspended_at),
        joined_at=user.date_joined,
        location=LocationType(
            state=user.state,
            state_code=user.state_code,
            city=user.city,
            district=user.district or None,
        ),
        seller_id=str(seller.id) if seller else None,
        admin_role=(user.admin_role or None) if user.is_staff else None,
    )


def admin_invitation_to_type(invitation):
    from .types import AdminInvitationType

    return AdminInvitationType(
        id=str(invitation.id),
        email=invitation.email,
        role=invitation.role,
        active=invitation.active,
        invited_by=(
            invitation.invited_by.full_name or invitation.invited_by.email
            if invitation.invited_by_id
            else None
        ),
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        revoked_at=invitation.revoked_at,
    )
