import strawberry


@strawberry.type
class PromotionOptionType:
    id: str
    name: str
    description: str
    duration_days: int
    price: float
