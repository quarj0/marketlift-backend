import strawberry
from django.db.models import Count, Exists, F, OuterRef, Q, Sum
from marketlift.graphql.auth import request_user, require_staff, require_seller
from sellers.models import SellerFollow, SellerProfile, SellerSettings
from subscriptions.services import get_effective_plan
from .mappers import admin_seller_to_type, seller_to_type
from .types import (
    AdminSellerType,
    SellerDashboardListingType,
    SellerDashboardPlanType,
    SellerSettingsType,
    SellerType,
    SellingDashboardType,
)


def seller_queryset(*, viewer=None, admin=False):
    qs = SellerProfile.objects.select_related("user")
    if not admin:
        qs = qs.filter(is_suspended=False, user__is_active=True)
    qs = qs.annotate(
        active_listing_count=Count(
            "listings",
            filter=Q(
                listings__status="published", listings__seller_deleted_at__isnull=True
            ),
            distinct=True,
        ),
        follower_count=Count("followers", distinct=True),
        total_conversations=Count("conversations", distinct=True),
        responded_conversations=Count(
            "conversations",
            filter=Q(conversations__messages__sender_id=F("user_id")),
            distinct=True,
        ),
        listing_count=Count("listings", distinct=True),
    )
    if viewer is not None and getattr(viewer, "is_authenticated", False):
        qs = qs.annotate(
            viewer_follows=Exists(
                SellerFollow.objects.filter(follower=viewer, seller_id=OuterRef("pk"))
            )
        )
    return qs


@strawberry.type
class SellerQuery:
    @strawberry.field
    def seller(self, info: strawberry.Info, id: strawberry.ID) -> SellerType | None:
        try:
            return seller_to_type(
                seller_queryset(viewer=request_user(info)).get(pk=str(id))
            )
        except (SellerProfile.DoesNotExist, ValueError):
            return None

    @strawberry.field
    def sellers(
        self,
        info: strawberry.Info,
        search: str | None = None,
        verified_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SellerType]:
        qs = seller_queryset(viewer=request_user(info))
        if search:
            qs = qs.filter(
                Q(display_name__icontains=search)
                | Q(user__full_name__icontains=search)
                | Q(user__city__icontains=search)
            )
        if verified_only:
            qs = qs.filter(verified_at__isnull=False)
        start = max(0, offset)
        return [seller_to_type(x) for x in qs[start : start + max(1, min(limit, 100))]]

    @strawberry.field
    def verified_sellers(
        self, info: strawberry.Info, limit: int = 20
    ) -> list[SellerType]:
        qs = seller_queryset(viewer=request_user(info)).filter(
            verified_at__isnull=False
        )
        return [seller_to_type(x) for x in qs[: max(1, min(limit, 100))]]

    @strawberry.field
    def my_followed_sellers(
        self, info: strawberry.Info, limit: int = 100
    ) -> list[SellerType]:
        viewer = request_user(info)
        if not viewer or not viewer.is_authenticated:
            from graphql import GraphQLError

            raise GraphQLError("Authentication required.")
        qs = seller_queryset(viewer=viewer).filter(followers__follower=viewer)
        return [seller_to_type(x) for x in qs[: max(1, min(limit, 200))]]

    @strawberry.field
    def my_seller_settings(self, info: strawberry.Info) -> SellerSettingsType:
        seller = require_seller(info)
        x = SellerSettings.objects.get_or_create(user_profile=seller)[0]
        return SellerSettingsType(
            new_inquiry=x.new_inquiry,
            listing_status=x.listing_status,
            performance=x.performance,
            auto_renew=x.auto_renew,
            show_phone=x.show_phone,
            vacation=x.vacation,
        )

    @strawberry.field
    def my_selling_dashboard(self, info: strawberry.Info) -> SellingDashboardType:
        seller = require_seller(info)
        from listings.models import Listing
        from messaging.models import Conversation

        listings = seller.listings.filter(seller_deleted_at__isnull=True)
        active = listings.filter(status=Listing.Status.PUBLISHED).count()
        drafts = listings.filter(status=Listing.Status.DRAFT).count()
        under_review = listings.filter(status=Listing.Status.UNDER_REVIEW).count()
        views = listings.aggregate(total=Sum("views"))["total"] or 0
        messages = Conversation.objects.filter(seller=seller).count()
        plan = get_effective_plan(seller)
        used = listings.filter(
            status__in=(
                Listing.Status.PUBLISHED,
                Listing.Status.PAUSED,
                Listing.Status.UNDER_REVIEW,
            )
        ).count()
        recent_qs = listings.annotate(
            inquiries=Count("conversations", distinct=True)
        ).order_by("-created_at")[:5]
        return SellingDashboardType(
            active=active,
            drafts=drafts,
            under_review=under_review,
            views=int(views),
            messages=messages,
            plan=SellerDashboardPlanType(
                name=plan.name if plan else "Free",
                code=plan.code if plan else "free",
                used=used,
                limit=plan.listing_limit if plan else 0,
            ),
            recent_listings=[
                SellerDashboardListingType(
                    id=str(x.id),
                    title=x.title,
                    status=x.status,
                    views=x.views,
                    inquiries=x.inquiries,
                    created_at=x.created_at,
                )
                for x in recent_qs
            ],
        )

    @strawberry.field
    def admin_sellers(
        self,
        info: strawberry.Info,
        search: str | None = None,
        suspended: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AdminSellerType]:
        require_staff(info, roles={"admin", "moderator", "support"})
        qs = seller_queryset(admin=True)
        if search:
            qs = qs.filter(
                Q(display_name__icontains=search)
                | Q(user__full_name__icontains=search)
                | Q(user__email__icontains=search)
            )
        if suspended is not None:
            qs = qs.filter(is_suspended=suspended)
        start = max(0, offset)
        return [
            admin_seller_to_type(x) for x in qs[start : start + max(1, min(limit, 100))]
        ]

    @strawberry.field
    def admin_seller(
        self, info: strawberry.Info, id: strawberry.ID
    ) -> AdminSellerType | None:
        require_staff(info, roles={"admin", "moderator", "support"})
        try:
            return admin_seller_to_type(seller_queryset(admin=True).get(pk=str(id)))
        except (SellerProfile.DoesNotExist, ValueError):
            return None
