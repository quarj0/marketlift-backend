from datetime import datetime
import strawberry
from strawberry.scalars import JSON


@strawberry.type
class SavedSearchType:
    id: strawberry.ID
    name: str
    criteria: JSON
    alerts_enabled: bool
    active: bool
    created_at: datetime
    last_checked_at: datetime | None
    last_notified_at: datetime | None
