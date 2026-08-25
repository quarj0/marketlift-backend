from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError

from marketlift.markets.service import profile_for_country_code


def _market(country_code: str):
    from platform_settings.models import Market

    profile = profile_for_country_code(country_code)
    market = Market.objects.filter(code=profile.country_code, is_enabled=True).first()
    if market is None:
        # No raw DoesNotExist should leak from a normal lookup. Catalog rows are
        # self-healing, but payment still fails safely if the market is truly
        # unavailable rather than guessing a currency/price.
        from platform_settings.market_catalog import ensure_market_catalog

        ensure_market_catalog()
        market = Market.objects.filter(
            code=profile.country_code, is_enabled=True
        ).first()
    if market is None:
        raise ValidationError("The selected market is not enabled.")
    return market


def seller_plan_price(*, plan, country_code: str, billing_cycle: str) -> Decimal:
    from platform_settings.models import SellerPlanMarketPrice
    from subscriptions.models import SellerSubscription

    market = _market(country_code)
    if plan.code == "free":
        return Decimal("0.00")
    try:
        row = SellerPlanMarketPrice.objects.get(market=market, plan=plan, active=True)
    except SellerPlanMarketPrice.DoesNotExist as exc:
        raise ValidationError(
            f"{plan.name} is not priced for {market.country_name}."
        ) from exc
    if billing_cycle == SellerSubscription.BillingCycle.YEARLY:
        return row.yearly_price
    if billing_cycle == SellerSubscription.BillingCycle.MONTHLY:
        return row.monthly_price
    raise ValidationError({"billingCycle": "Invalid billing cycle."})


def promotion_price(*, product, country_code: str) -> Decimal:
    from platform_settings.models import PromotionProductMarketPrice

    market = _market(country_code)
    try:
        row = PromotionProductMarketPrice.objects.get(
            market=market, product=product, active=True
        )
    except PromotionProductMarketPrice.DoesNotExist as exc:
        raise ValidationError(
            f"{product.name} is not priced for {market.country_name}."
        ) from exc
    return row.price


def market_pricing_readiness(market) -> tuple[bool, list[str]]:
    """Return whether an enabled market has every required active price."""
    from promotions.models import PromotionProduct
    from subscriptions.models import SellerPlan
    from platform_settings.models import (
        PromotionProductMarketPrice,
        SellerPlanMarketPrice,
    )

    problems: list[str] = []
    paid_plans = SellerPlan.objects.filter(active=True).exclude(code="free")
    plan_rows = {
        row.plan_id: row
        for row in SellerPlanMarketPrice.objects.filter(market=market, active=True)
    }
    for plan in paid_plans:
        row = plan_rows.get(plan.id)
        if row is None:
            problems.append(f"Missing seller plan price: {plan.code}")
        elif row.monthly_price <= 0 or row.yearly_price <= 0:
            problems.append(
                f"Invalid seller plan price: {plan.code} must have positive monthly and yearly prices"
            )

    products = PromotionProduct.objects.filter(active=True)
    product_rows = {
        row.product_id: row
        for row in PromotionProductMarketPrice.objects.filter(
            market=market, active=True
        )
    }
    for product in products:
        row = product_rows.get(product.id)
        if row is None:
            problems.append(f"Missing promotion price: {product.code}")
        elif row.price <= 0:
            problems.append(
                f"Invalid promotion price: {product.code} must be greater than zero"
            )
    return not problems, problems
