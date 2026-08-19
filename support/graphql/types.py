from datetime import datetime
import strawberry


@strawberry.type
class SupportMessageType:
    id: strawberry.ID
    sender_name: str | None
    body: str
    internal: bool
    attachment_url: str | None
    created_at: datetime


@strawberry.type
class SupportTicketType:
    id: strawberry.ID
    reference: str
    user_id: strawberry.ID
    user_name: str
    subject: str
    category: str
    priority: str
    status: str
    assigned_to: str | None
    updated_at: datetime
    created_at: datetime
    messages: list[SupportMessageType]
