import strawberry
from strawberry.scalars import JSON


@strawberry.input
class ListingFilterInput:
    q: str | None = None
    category: str | None = None
    state: str | None = None
    city: str | None = None
    district: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    condition: str | None = None
    seller_type: str | None = None
    verified_only: bool = False
    date_listed: str | None = None
    sort: str = "relevant"


@strawberry.input
class ListingInput:
    category_id: str
    title: str
    description: str
    state: str
    state_code: str
    city: str
    price: float | None = None
    condition: str = ""
    district: str = ""
    negotiable: bool = False
    attributes: JSON | None = None
    image_urls: list[str] | None = None
    image_upload_ids: list[strawberry.ID] | None = None
