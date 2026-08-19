import strawberry
from django.core.exceptions import ValidationError
from graphql import GraphQLError

from marketlift.graphql.auth import request_from_info, require_seller, require_staff
from marketlift.graphql.errors import validation_error
from subscriptions.models import SellerPlan
from subscriptions.services import (
    cancel_subscription,
    create_seller_plan,
    update_seller_plan,
)
from .mappers import plan_to_type, subscription_to_type
from .types import SellerPlanType, SellerSubscriptionType


@strawberry.type
class SubscriptionMutation:
    @strawberry.mutation
    def cancel_my_subscription(
        self, info: strawberry.Info, at_period_end: bool = True
    ) -> SellerSubscriptionType:
        seller = require_seller(info)
        try:
            item = cancel_subscription(
                seller=seller,
                actor=seller.user,
                at_period_end=at_period_end,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(exc) from exc
        return subscription_to_type(item)

    @strawberry.mutation
    def create_seller_plan(
        self,
        info: strawberry.Info,
        name: str,
        monthly_price: float,
        listing_limit: int,
        promotion_credits: int,
        code: str = "",
        yearly_price: float = 0,
        visibility_weight: float = 1,
        recommended: bool = False,
        features: list[str] | None = None,
        active: bool = True,
    ) -> SellerPlanType:
        actor = require_staff(info, roles={"admin", "finance"})
        try:
            plan = create_seller_plan(
                code=code,
                name=name,
                monthly_price=monthly_price,
                yearly_price=yearly_price,
                listing_limit=listing_limit,
                promotion_credits=promotion_credits,
                visibility_weight=visibility_weight,
                recommended=recommended,
                features=features,
                active=active,
                actor=actor,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(exc) from exc
        return plan_to_type(plan)

    @strawberry.mutation
    def update_seller_plan(
        self,
        info: strawberry.Info,
        id: str,
        name: str,
        monthly_price: float,
        yearly_price: float,
        listing_limit: int,
        promotion_credits: int,
        visibility_weight: float,
        recommended: bool,
        features: list[str],
        active: bool = True,
    ) -> SellerPlanType:
        actor = require_staff(info, roles={"admin", "finance"})
        try:
            plan = SellerPlan.objects.get(code=id)
        except SellerPlan.DoesNotExist as exc:
            raise GraphQLError("Seller plan not found.") from exc
        try:
            plan = update_seller_plan(
                plan=plan,
                name=name,
                monthly_price=monthly_price,
                yearly_price=yearly_price,
                listing_limit=listing_limit,
                promotion_credits=promotion_credits,
                visibility_weight=visibility_weight,
                recommended=recommended,
                features=features,
                active=active,
                actor=actor,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(exc) from exc
        return plan_to_type(plan)
