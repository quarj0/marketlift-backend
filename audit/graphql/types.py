from datetime import datetime
import strawberry
from strawberry.scalars import JSON


@strawberry.type
class AuditEventType:
    id: strawberry.ID
    actor_name: str
    actor_email: str | None
    action: str
    target_type: str
    target_id: str
    target_label: str
    metadata: JSON
    ip_address: str | None
    created_at: datetime
