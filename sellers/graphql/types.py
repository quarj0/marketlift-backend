from datetime import datetime

import strawberry

from marketlift.graphql.types import LocationType


@strawberry.type
class SellerType:
    id: strawberry.ID
    name: str
    verified: bool
    seller_type: str
    is_suspended: bool
    rating: float
    reviews: int
    positive_review_percent: float
    location: LocationType


@strawberry.type
class AdminSellerType:
    id: strawberry.ID
    user_id: strawberry.ID
    name: str
    email: str
    seller_type: str
    verified: bool
    suspended: bool
    activated_at: datetime
    suspended_at: datetime | None
    suspension_reason: str | None
    listing_count: int


@strawberry.type
class SellerSettingsType:
    new_inquiry: bool
    listing_status: bool
    performance: bool
    auto_renew: bool
    show_phone: bool
    vacation: bool


@strawberry.input
class SellerSettingsInput:
    new_inquiry: bool | None = None
    listing_status: bool | None = None
    performance: bool | None = None
    auto_renew: bool | None = None
    show_phone: bool | None = None
    vacation: bool | None = None
