import strawberry
from audit.models import AuditEvent
from marketlift.graphql.auth import require_staff
from .types import AuditEventType


def _map(x):
    return AuditEventType(
        id=str(x.id),
        actor_name=x.actor_name,
        actor_email=x.actor_email or None,
        action=x.action,
        target_type=x.target_type,
        target_id=x.target_id,
        target_label=x.target_label,
        metadata=x.metadata,
        ip_address=x.ip_address,
        created_at=x.created_at,
    )


@strawberry.type
class AuditQuery:
    @strawberry.field
    def audit_events(
        self,
        info: strawberry.Info,
        action: str | None = None,
        target_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEventType]:
        require_staff(info, roles={"admin", "moderator"})
        qs = AuditEvent.objects.all()
        if action:
            qs = qs.filter(action=action)
        if target_type:
            qs = qs.filter(target_type=target_type)
        start = max(0, offset)
        end = start + max(1, min(limit, 200))
        return [_map(x) for x in qs[start:end]]
