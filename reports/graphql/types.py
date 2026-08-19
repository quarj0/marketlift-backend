from datetime import datetime
import strawberry


@strawberry.type
class ReportType:
    id: strawberry.ID
    reference: str
    target_type: str
    target_id: str
    target_label: str
    reason: str
    statement: str
    priority: str
    status: str
    reporter_name: str | None
    assigned_to: str | None
    internal_note: str | None
    decision_reason: str | None
    created_at: datetime
    decided_at: datetime | None
