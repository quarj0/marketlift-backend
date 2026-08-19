import strawberry
from promotions.models import PromotionProduct
from .types import PromotionOptionType


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
