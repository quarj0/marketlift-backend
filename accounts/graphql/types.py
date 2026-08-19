from datetime import datetime

import strawberry


@strawberry.type
class SellerCapabilityType:
    seller_id: strawberry.ID
    activated_at: datetime
    verified: bool
    suspended: bool


@strawberry.type
class AccountType:
    id: strawberry.ID
    name: str
    email: str
    phone: str | None
    avatar_url: str | None
    bio: str | None
    state: str
    state_code: str
    city: str
    district: str | None
    email_verified: bool
    phone_verified: bool
    active: bool
    staff: bool
    seller_profile: SellerCapabilityType | None


@strawberry.type
class AdminUserType:
    id: strawberry.ID
    name: str
    email: str
    phone: str | None
    active: bool
    staff: bool
    seller_enabled: bool
    created_at: datetime
    suspended_at: datetime | None
    suspension_reason: str | None
