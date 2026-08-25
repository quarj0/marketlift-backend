from datetime import datetime

import strawberry

from marketlift.graphql.types import LocationType


@strawberry.type
class SellerType:
    id: strawberry.ID
    name: str
    avatar_url: str | None
    phone: str | None
    verified: bool
    seller_type: str
    country_code: str
    is_suspended: bool
    rating: float
    reviews: int
    positive_review_percent: float
    response_rate: float | None
    active_listings: int
    follower_count: int
    is_followed: bool
    member_since: datetime
    location: LocationType


@strawberry.type
class AdminSellerType:
    id: strawberry.ID
    user_id: strawberry.ID
    name: str
    email: str
    seller_type: str
    country_code: str
    verified: bool
    suspended: bool
    activated_at: datetime
    suspended_at: datetime | None
    suspension_reason: str | None
    listing_count: int


@strawberry.input
class SellerProfileInput:
    display_name: str | None = None
    seller_type: str | None = None


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


@strawberry.type
class SellerDashboardPlanType:
    name: str
    code: str
    used: int
    limit: int


@strawberry.type
class SellerDashboardListingType:
    id: strawberry.ID
    title: str
    status: str
    views: int
    inquiries: int
    created_at: datetime


@strawberry.type
class SellingDashboardType:
    active: int
    drafts: int
    under_review: int
    views: int
    messages: int
    plan: SellerDashboardPlanType
    recent_listings: list[SellerDashboardListingType]
