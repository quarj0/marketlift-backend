from datetime import datetime

import strawberry


@strawberry.type
class ConversationUserType:
    id: strawberry.ID
    name: str
    avatar_url: str | None
    verified_seller: bool
    is_seller: bool


@strawberry.type
class ConversationListingType:
    id: strawberry.ID | None
    slug: str | None
    title: str
    price: float | None
    primary_image: str | None
    status: str | None
    deleted: bool


@strawberry.type
class MessageAttachmentType:
    type: str
    url: str
    name: str
    mime_type: str
    size: int


@strawberry.type
class MessageType:
    id: strawberry.ID
    conversation_id: strawberry.ID
    sender_id: strawberry.ID
    sender: str
    text: str
    created_at: datetime
    read: bool
    attachment: MessageAttachmentType | None


@strawberry.type
class ConversationType:
    id: strawberry.ID
    participant: ConversationUserType
    listing: ConversationListingType
    last_message: str
    last_message_at: datetime | None
    unread: int
    archived: bool
    blocked: bool
