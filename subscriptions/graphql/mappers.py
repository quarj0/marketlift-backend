from .types import SellerPlanType


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
    )
