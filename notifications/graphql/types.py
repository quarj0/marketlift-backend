from datetime import datetime
import strawberry
from strawberry.scalars import JSON


@strawberry.type
class NotificationType:
    id: strawberry.ID
    type: str
    title: str
    body: str
    created_at: datetime
    read: bool
    href: str | None
    data: JSON
