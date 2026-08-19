import strawberry


@strawberry.input
class CreateSupportTicketInput:
    subject: str
    category: str
    message: str
    upload_id: strawberry.ID | None = None
