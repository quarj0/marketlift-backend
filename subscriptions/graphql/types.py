import strawberry


@strawberry.type
class SellerPlanType:
    id: str
    name: str
    monthly_price: float
    yearly_price: float
    listing_limit: int
    promotion_credits: int
    features: list[str]
    visibility_weight: float
    recommended: bool
