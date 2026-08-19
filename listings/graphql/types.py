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
    status: str
    views: int
    negotiable: bool
    attributes: JSON
    featured: bool
    urgent: bool
    favorites: int
