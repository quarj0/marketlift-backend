from .types import SellerPlanType, SellerSubscriptionType


def plan_to_type(plan):
    return SellerPlanType(
        id=plan.code,
        name=plan.name,
        monthly_price=float(plan.monthly_price),
        yearly_price=float(plan.yearly_price),
        listing_limit=plan.listing_limit,
        promotion_credits=plan.promotion_credits,
        features=list(plan.features),
        visibility_weight=float(plan.visibility_weight),
        recommended=plan.recommended,
        active=plan.active,
        sort_order=plan.sort_order,
    )


def subscription_to_type(item):
    return SellerSubscriptionType(
        id=str(item.id),
        seller_id=str(item.seller_id),
        seller_name=item.seller.display_name
        or item.seller.user.full_name
        or item.seller.user.email,
        plan=plan_to_type(item.plan),
        billing_cycle=item.billing_cycle,
        status=item.status,
        current_period_start=item.current_period_start,
        current_period_end=item.current_period_end,
        cancel_at_period_end=item.cancel_at_period_end,
        promotion_credits_remaining=item.promotion_credits_remaining,
    )
