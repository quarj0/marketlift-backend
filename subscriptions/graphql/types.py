from datetime import datetime
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
    active: bool
    sort_order: int


@strawberry.type
class SellerSubscriptionType:
    id: strawberry.ID
    seller_id: strawberry.ID
    seller_name: str
    plan: SellerPlanType
    billing_cycle: str
    status: str
    current_period_start: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    promotion_credits_remaining: int
