import strawberry
from django.db.models import Q
from marketlift.graphql.auth import require_staff, require_user
from listings.models import RecentlyViewedListing, SavedListing
from messaging.models import Message
from reviews.models import SellerReview
from accounts.services import get_account_settings
from .mappers import admin_user_to_type, settings_to_type, user_to_type
from .types import (
    AccountOverviewType,
    AccountSettingsType,
    AccountUserType,
    AdminUserType,
)


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
        seller = getattr(u, "seller_profile", None)
        unread = 0
        from messaging.models import Conversation

        for c in Conversation.objects.filter(
            Q(buyer=u) | Q(seller__user=u)
        ).select_related("seller__user")[:500]:
            unread += c.unread_count_for(u)
        return AccountOverviewType(
            saved_count=SavedListing.objects.filter(user=u).count(),
            unread_messages=unread,
            reviews_count=SellerReview.objects.filter(reviewer=u).count(),
            recently_viewed_count=RecentlyViewedListing.objects.filter(user=u).count(),
        )

    @strawberry.field
    def admin_users(
        self, info: strawberry.Info, q: str | None = None, limit: int = 100
    ) -> list[AdminUserType]:
        require_staff(info)
        from accounts.models import User

        qs = User.objects.select_related("seller_profile")
        if q:
            qs = qs.filter(
                Q(email__icontains=q)
                | Q(full_name__icontains=q)
                | Q(phone__icontains=q)
            )
        return [admin_user_to_type(x) for x in qs[: max(1, min(limit, 200))]]
