from datetime import datetime
import strawberry


@strawberry.type
class PromotionOptionType:
    id: str
    name: str
    description: str
    duration_days: int
    price: float
    country_code: str = ""
    currency: str = ""


@strawberry.type
class ListingPromotionType:
    id: strawberry.ID
    listing_id: strawberry.ID
    product_id: str
    source: str
    starts_at: datetime
    ends_at: datetime
    active: bool
