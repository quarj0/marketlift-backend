from datetime import datetime
import strawberry


@strawberry.type
class ReviewType:
    id: strawberry.ID
    seller_id: strawberry.ID
    seller_name: str
    seller_avatar: str | None
    reviewer_id: strawberry.ID
    reviewer_name: str
    listing_id: strawberry.ID | None
    listing_title: str | None
    rating: int
    comment: str
    date: datetime
    seller_reply: str | None


@strawberry.type
class SellerReputationType:
    average: float
    total: int
    positive_percent: float
    one_star: int
    two_star: int
    three_star: int
    four_star: int
    five_star: int
