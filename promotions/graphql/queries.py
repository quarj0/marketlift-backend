import strawberry
from django.core.exceptions import ValidationError

from marketlift.markets.pricing import promotion_price
from marketlift.markets.service import active_market_profile, profile_for_country_code
from promotions.models import PromotionProduct
from .types import PromotionOptionType, ListingPromotionType


@strawberry.type
class PromotionQuery:
    @strawberry.field
    def promotion_options(
        self, country_code: str | None = None
    ) -> list[PromotionOptionType]:
        profile = profile_for_country_code(
            country_code or active_market_profile().country_code
        )
        rows: list[PromotionOptionType] = []
        for product in PromotionProduct.objects.filter(active=True):
            try:
                price = promotion_price(
                    product=product, country_code=profile.country_code
                )
            except ValidationError:
                continue
            rows.append(
                PromotionOptionType(
                    id=product.code,
                    name=product.name,
                    description=product.description,
                    duration_days=product.duration_days,
                    price=float(price),
                    country_code=profile.country_code,
                    currency=profile.currency,
                )
            )
        return rows

    @strawberry.field
    def my_listing_promotions(
        self, info: strawberry.Info, listing_id: strawberry.ID | None = None
    ) -> list[ListingPromotionType]:
        from marketlift.graphql.auth import require_seller
        from promotions.models import ListingPromotion

        seller = require_seller(info)
        qs = ListingPromotion.objects.select_related("listing", "product").filter(
            listing__seller=seller
        )
        if listing_id is not None:
            qs = qs.filter(listing_id=str(listing_id))
        return [
            ListingPromotionType(
                id=str(x.id),
                listing_id=str(x.listing_id),
                product_id=x.product.code,
                source=x.source,
                starts_at=x.starts_at,
                ends_at=x.ends_at,
                active=x.is_active,
            )
            for x in qs
        ]
