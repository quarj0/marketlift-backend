from datetime import datetime
import strawberry
from listings.graphql.types import ListingType


@strawberry.type
class ModerationCaseType:
    id: strawberry.ID
    status: str
    source: str
    review_reason: str
    decision_reason: str | None
    opened_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    listing: ListingType
