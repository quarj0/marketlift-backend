import strawberry
from django.db.models import F, Q
from marketlift.graphql.auth import require_staff, require_user
from listings.graphql.mappers import listing_queryset, listing_to_type
from listings.models import Listing, RecentlyViewedListing, SavedListing
from messaging.models import Message
from reviews.models import SellerReview
from accounts.services import get_account_settings
from .mappers import (
    admin_invitation_to_type,
    admin_user_to_type,
    settings_to_type,
    user_to_type,
)
from .types import (
    AccountOverviewType,
    AccountSettingsType,
    AccountUserType,
    AdminInvitationType,
    AdminUserType,
)


def _unread_message_count(user):
    return Message.objects.filter(
        ~Q(sender=user),
        Q(
            Q(conversation__buyer=user)
            & (
                Q(conversation__buyer_last_read_at__isnull=True)
                | Q(created_at__gt=F("conversation__buyer_last_read_at"))
            )
        )
        | Q(
            Q(conversation__seller__user=user)
            & (
                Q(conversation__seller_last_read_at__isnull=True)
                | Q(created_at__gt=F("conversation__seller_last_read_at"))
            )
        ),
    ).count()


@strawberry.type
class AccountQuery:
    @strawberry.field
    def me(self, info: strawberry.Info) -> AccountUserType:
        return user_to_type(require_user(info))

    @strawberry.field
    def my_account_settings(self, info: strawberry.Info) -> AccountSettingsType:
        return settings_to_type(get_account_settings(require_user(info)))

    @strawberry.field
    def my_account_overview(self, info: strawberry.Info) -> AccountOverviewType:
        u = require_user(info)
        recent_ids = list(
            RecentlyViewedListing.objects.filter(user=u).values_list(
                "listing_id", flat=True
            )[:6]
        )
        recent_rows = {
            x.id: x
            for x in listing_queryset(Listing.objects.public()).filter(
                id__in=recent_ids
            )
        }
        recent = [
            listing_to_type(recent_rows[i]) for i in recent_ids if i in recent_rows
        ]
        saved = [
            listing_to_type(x)
            for x in listing_queryset(Listing.objects.public()).filter(
                saved_by__user=u
            )[:6]
        ]
        return AccountOverviewType(
            saved_count=SavedListing.objects.filter(user=u).count(),
            unread_messages=_unread_message_count(u),
            reviews_count=SellerReview.objects.filter(reviewer=u).count(),
            recently_viewed_count=RecentlyViewedListing.objects.filter(user=u).count(),
            recently_viewed=recent,
            saved_listings=saved,
        )

    @strawberry.field
    def admin_users(
        self,
        info: strawberry.Info,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AdminUserType]:
        require_staff(info, roles={"admin", "moderator", "support"})
        from accounts.models import User

        qs = User.objects.select_related("seller_profile")
        if q:
            qs = qs.filter(
                Q(email__icontains=q)
                | Q(full_name__icontains=q)
                | Q(phone__icontains=q)
            )
        start = max(0, offset)
        return [
            admin_user_to_type(x) for x in qs[start : start + max(1, min(limit, 200))]
        ]

    @strawberry.field
    def admin_user(
        self, info: strawberry.Info, id: strawberry.ID
    ) -> AdminUserType | None:
        require_staff(info, roles={"admin", "moderator", "support"})
        from accounts.models import User

        try:
            return admin_user_to_type(
                User.objects.select_related("seller_profile").get(pk=str(id))
            )
        except (User.DoesNotExist, ValueError):
            return None

    @strawberry.field
    def admin_staff(
        self, info: strawberry.Info, limit: int = 100
    ) -> list[AdminUserType]:
        require_staff(info, roles={"admin"})
        from accounts.models import User

        return [
            admin_user_to_type(x)
            for x in User.objects.select_related("seller_profile").filter(
                is_staff=True
            )[: max(1, min(limit, 200))]
        ]

    @strawberry.field
    def admin_invitations(
        self, info: strawberry.Info, include_inactive: bool = False, limit: int = 100
    ) -> list[AdminInvitationType]:
        require_staff(info, roles={"admin"})
        from accounts.models import AdminInvitation
        from django.utils import timezone

        qs = AdminInvitation.objects.select_related("invited_by")
        if not include_inactive:
            qs = qs.filter(
                accepted_at__isnull=True,
                revoked_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
        return [admin_invitation_to_type(x) for x in qs[: max(1, min(limit, 200))]]
