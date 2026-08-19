import strawberry
from django.db.models import Q

from marketlift.graphql.auth import require_seller, require_staff
from subscriptions.models import SellerPlan, SellerSubscription
from subscriptions.services import get_active_subscription, get_effective_plan
from .mappers import plan_to_type, subscription_to_type
from .types import SellerPlanType, SellerSubscriptionType


@strawberry.type
class SubscriptionQuery:
    @strawberry.field
    def seller_plans(self) -> list[SellerPlanType]:
        return [plan_to_type(plan) for plan in SellerPlan.objects.filter(active=True)]

    @strawberry.field
    def my_seller_plan(self, info: strawberry.Info) -> SellerPlanType | None:
        plan = get_effective_plan(require_seller(info))
        return plan_to_type(plan) if plan else None

    @strawberry.field
    def my_subscription(self, info: strawberry.Info) -> SellerSubscriptionType | None:
        item = get_active_subscription(require_seller(info))
        return subscription_to_type(item) if item else None

    @strawberry.field
    def admin_seller_plans(self, info: strawberry.Info) -> list[SellerPlanType]:
        require_staff(info)
        return [plan_to_type(plan) for plan in SellerPlan.objects.all()]

    @strawberry.field
    def admin_subscriptions(
        self,
        info: strawberry.Info,
        search: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SellerSubscriptionType]:
        require_staff(info)
        qs = SellerSubscription.objects.select_related(
            "plan", "seller", "seller__user"
        ).all()
        if search:
            qs = qs.filter(
                Q(seller__display_name__icontains=search)
                | Q(seller__user__email__icontains=search)
                | Q(plan__name__icontains=search)
            )
        if status:
            qs = qs.filter(status=status)
        start = max(0, offset)
        end = start + max(1, min(limit, 100))
        return [subscription_to_type(item) for item in qs[start:end]]
