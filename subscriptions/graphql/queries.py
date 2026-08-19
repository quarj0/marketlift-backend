import strawberry
from subscriptions.models import SellerPlan
from subscriptions.services import get_effective_plan
from marketlift.graphql.auth import require_seller
from .mappers import plan_to_type
from .types import SellerPlanType


@strawberry.type
class SubscriptionQuery:
    @strawberry.field
    def seller_plans(self) -> list[SellerPlanType]:
        return [plan_to_type(p) for p in SellerPlan.objects.filter(active=True)]

    @strawberry.field
    def my_seller_plan(self, info: strawberry.Info) -> SellerPlanType | None:
        plan = get_effective_plan(require_seller(info))
        return plan_to_type(plan) if plan else None
