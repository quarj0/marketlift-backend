from marketlift.markets.pricing import market_pricing_readiness
from platform_settings.models import (
    Market,
    PlatformConfiguration,
    PromotionProductMarketPrice,
    SellerPlanMarketPrice,
)

from .types import (
    MarketType,
    PlatformConfigurationType,
    PromotionMarketPriceType,
    SellerPlanMarketPriceType,
)


def config_to_type(config: PlatformConfiguration) -> PlatformConfigurationType:
    return PlatformConfigurationType(
        marketplace_name=config.marketplace_name,
        support_email=config.support_email,
        allow_new_registrations=config.allow_new_registrations,
        allow_seller_activation=config.allow_seller_activation,
        maintenance_mode=config.maintenance_mode,
        automated_listing_flagging=config.automated_listing_flagging,
        seller_verification_required=config.seller_verification_required,
        default_listing_duration_days=config.default_listing_duration_days,
        max_listing_images=config.max_listing_images,
        high_risk_threshold=config.high_risk_threshold,
        admin_email_operational_alerts=config.admin_email_operational_alerts,
        admin_verification_queue_alerts=config.admin_verification_queue_alerts,
        admin_payment_failure_alerts=config.admin_payment_failure_alerts,
        feature_flags=config.feature_flags,
    )


def market_to_type(market: Market) -> MarketType:
    ready, issues = market_pricing_readiness(market)
    return MarketType(
        code=market.code,
        country_name=market.country_name,
        locale=market.locale,
        currency=market.currency,
        currency_symbol=market.currency_symbol,
        timezone=market.timezone,
        payment_provider=market.payment_provider,
        payment_methods=list(market.payment_methods or []),
        identity_provider=market.identity_provider,
        identity_label=market.identity_label,
        identity_key=market.identity_key,
        location_mode=(
            "catalog" if market.hierarchical_location_catalog else "geocoder"
        ),
        is_enabled=market.is_enabled,
        is_default=market.is_default,
        sort_order=market.sort_order,
        pricing_ready=ready,
        pricing_issues=issues,
    )


def seller_plan_market_price_to_type(
    row: SellerPlanMarketPrice,
) -> SellerPlanMarketPriceType:
    return SellerPlanMarketPriceType(
        market_code=row.market.code,
        currency=row.market.currency,
        plan_id=row.plan.code,
        plan_name=row.plan.name,
        monthly_price=float(row.monthly_price),
        yearly_price=float(row.yearly_price),
        active=row.active,
    )


def promotion_market_price_to_type(
    row: PromotionProductMarketPrice,
) -> PromotionMarketPriceType:
    return PromotionMarketPriceType(
        market_code=row.market.code,
        currency=row.market.currency,
        promotion_id=row.product.code,
        promotion_name=row.product.name,
        price=float(row.price),
        active=row.active,
    )
