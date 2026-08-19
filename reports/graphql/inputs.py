import strawberry


@strawberry.input
class ReportInput:
    target_type: str
    target_id: strawberry.ID
    reason: str
    statement: str
    priority: str = "medium"
