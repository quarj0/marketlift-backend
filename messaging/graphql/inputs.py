import strawberry


@strawberry.input
class SendMessageInput:
    conversation_id: strawberry.ID
    text: str | None = None
    upload_id: strawberry.ID | None = None
