from datetime import datetime
import strawberry
from strawberry.scalars import JSON
from marketlift.graphql.types import LocationType
from sellers.graphql.types import SellerType


@strawberry.type
class ListingType:
    id: strawberry.ID
    slug: str
    title: str
    description: str
    price: float | None
    category: str
    category_name: str
    category_schema_version: int
    condition: str | None
    location: LocationType
    images: list[str]
    seller: SellerType
    created_at: datetime
    expires_at: datetime | None
    status: str
    views: int
    negotiable: bool
    attributes: JSON
    featured: bool
    urgent: bool
    favorites: int
    inquiries: int
    seller_deleted_at: datetime | None
    distance_km: float | None = None


@strawberry.type
class ListingPageInfoType:
    has_next_page: bool
    end_cursor: str | None


@strawberry.type
class ListingConnectionType:
    items: list[ListingType]
    page_info: ListingPageInfoType
    total_count: int
