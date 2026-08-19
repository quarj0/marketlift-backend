from datetime import datetime
import strawberry
from marketlift.graphql.types import LocationType
from strawberry.scalars import JSON
from listings.graphql.types import ListingType


@strawberry.type
class SellerCapabilityType:
    seller_id: strawberry.ID
    activated_at: datetime
    verified: bool
    suspended: bool


@strawberry.type
class AccountUserType:
    id: strawberry.ID
    name: str
    email: str
    phone: str | None
    avatar_url: str | None
    bio: str | None
    location: LocationType
    email_verified: bool
    phone_verified: bool
    member_since: datetime
    active: bool
    staff: bool
    seller_profile: SellerCapabilityType | None


@strawberry.type
class AccountSettingsType:
    language: str
    currency: str
    email_messages: bool
    email_listing_updates: bool
    email_recommendations: bool
    push_messages: bool
    push_listing_updates: bool
    marketing_emails: bool
    show_phone_to_sellers: bool
    show_online_status: bool


@strawberry.input
class AccountProfileInput:
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    bio: str | None = None
    state: str | None = None
    state_code: str | None = None
    city: str | None = None
    district: str | None = None
    avatar_upload_id: strawberry.ID | None = None


@strawberry.input
class AccountSettingsInput:
    language: str | None = None
    email_messages: bool | None = None
    email_listing_updates: bool | None = None
    email_recommendations: bool | None = None
    push_messages: bool | None = None
    push_listing_updates: bool | None = None
    marketing_emails: bool | None = None
    show_phone_to_sellers: bool | None = None
    show_online_status: bool | None = None


@strawberry.type
class AccountOverviewType:
    saved_count: int
    unread_messages: int
    reviews_count: int
    recently_viewed_count: int
    recently_viewed: list["ListingType"]
    saved_listings: list["ListingType"]


@strawberry.type
class AdminUserType:
    id: strawberry.ID
    name: str
    email: str
    phone: str | None
    active: bool
    staff: bool
    suspended: bool
    joined_at: datetime
    location: LocationType
    seller_id: strawberry.ID | None
    admin_role: str | None


@strawberry.type
class AdminInvitationType:
    id: strawberry.ID
    email: str
    role: str
    active: bool
    invited_by: str | None
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
