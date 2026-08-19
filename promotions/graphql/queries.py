import strawberry
from promotions.models import PromotionProduct
from .types import PromotionOptionType, ListingPromotionType


@strawberry.type
class PromotionQuery:
    @strawberry.field
    def promotion_options(self) -> list[PromotionOptionType]:
        return [
            PromotionOptionType(
                id=p.code,
                name=p.name,
                description=p.description,
                duration_days=p.duration_days,
                price=float(p.price),
            )
            for p in PromotionProduct.objects.filter(active=True)
        ]

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
