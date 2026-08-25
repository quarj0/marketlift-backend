from django.core.exceptions import ValidationError

from marketlift.markets.pricing import seller_plan_price
from marketlift.markets.service import profile_for_country_code

from .types import SellerPlanType, SellerSubscriptionType


def plan_to_type(plan, *, country_code: str | None = None):
    monthly = plan.monthly_price
    yearly = plan.yearly_price
    currency = ""
    normalized_country = ""
    if country_code:
        profile = profile_for_country_code(country_code)
        normalized_country = profile.country_code
        currency = profile.currency
        monthly = seller_plan_price(
            plan=plan, country_code=profile.country_code, billing_cycle="monthly"
        )
        yearly = seller_plan_price(
            plan=plan, country_code=profile.country_code, billing_cycle="yearly"
        )
    return SellerPlanType(
        id=plan.code,
        name=plan.name,
        monthly_price=float(monthly),
        yearly_price=float(yearly),
        listing_limit=plan.listing_limit,
        promotion_credits=plan.promotion_credits,
        features=list(plan.features),
        visibility_weight=float(plan.visibility_weight),
        recommended=plan.recommended,
        active=plan.active,
        sort_order=plan.sort_order,
        country_code=normalized_country,
        currency=currency,
    )


def subscription_to_type(item):
    return SellerSubscriptionType(
        id=str(item.id),
        seller_id=str(item.seller_id),
        seller_name=item.seller.display_name
        or item.seller.user.full_name
        or item.seller.user.email,
        plan=plan_to_type(item.plan, country_code=item.seller.country_code),
        billing_cycle=item.billing_cycle,
        status=item.status,
        current_period_start=item.current_period_start,
        current_period_end=item.current_period_end,
        cancel_at_period_end=item.cancel_at_period_end,
        promotion_credits_remaining=item.promotion_credits_remaining,
    )
