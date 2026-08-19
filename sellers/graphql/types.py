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
