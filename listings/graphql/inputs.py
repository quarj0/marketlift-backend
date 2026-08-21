import strawberry
from strawberry.scalars import JSON


@strawberry.input
class ListingFilterInput:
    q: str | None = None
    category: str | None = None
    country_code: str | None = None
    state: str | None = None
    city: str | None = None
    district: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    radius_km: float | None = None
    min_price: float | None = None
    max_price: float | None = None
    condition: str | None = None
    seller_type: str | None = None
    seller_id: strawberry.ID | None = None
    verified_only: bool = False
    date_listed: str | None = None
    attribute_filters: JSON | None = None
    sort: str = "relevant"


@strawberry.input
class ListingInput:
    category_id: str
    title: str
    description: str
    state: str = ""
    state_code: str = ""
    city: str = ""
    country_code: str = ""
    latitude: float | None = None
    longitude: float | None = None
    location_token: str | None = None
    price: float | None = None
    condition: str = ""
    district: str = ""
    negotiable: bool = False
    attributes: JSON | None = None
    image_urls: list[str] | None = None
    image_upload_ids: list[strawberry.ID] | None = None
