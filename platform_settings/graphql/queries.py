import strawberry

from marketlift.graphql.auth import require_staff
from platform_settings.models import (
    Market,
    PlatformConfiguration,
    PromotionProductMarketPrice,
    SellerPlanMarketPrice,
)

from .mappers import (
    config_to_type,
    market_to_type,
    promotion_market_price_to_type,
    seller_plan_market_price_to_type,
)
from .types import (
    MarketType,
    PlatformConfigurationType,
    PromotionMarketPriceType,
    SellerPlanMarketPriceType,
)


@strawberry.type
class PlatformSettingsQuery:
    @strawberry.field
    def platform_configuration(
        self, info: strawberry.Info
    ) -> PlatformConfigurationType:
        require_staff(info, roles={"admin"})
        return config_to_type(PlatformConfiguration.load())

    @strawberry.field
    def admin_markets(self, info: strawberry.Info) -> list[MarketType]:
        require_staff(info, roles={"admin", "finance"})
        return [market_to_type(row) for row in Market.objects.all()]

    @strawberry.field
    def admin_seller_plan_market_prices(
        self, info: strawberry.Info, market_code: str | None = None
    ) -> list[SellerPlanMarketPriceType]:
        require_staff(info, roles={"admin", "finance"})
        qs = SellerPlanMarketPrice.objects.select_related("market", "plan")
        if market_code:
            qs = qs.filter(market__code=market_code.strip().upper())
        return [seller_plan_market_price_to_type(row) for row in qs]

    @strawberry.field
    def admin_promotion_market_prices(
        self, info: strawberry.Info, market_code: str | None = None
    ) -> list[PromotionMarketPriceType]:
        require_staff(info, roles={"admin", "finance"})
        qs = PromotionProductMarketPrice.objects.select_related("market", "product")
        if market_code:
            qs = qs.filter(market__code=market_code.strip().upper())
        return [promotion_market_price_to_type(row) for row in qs]
