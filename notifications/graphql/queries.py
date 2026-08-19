import strawberry
from marketlift.graphql.auth import require_user
from notifications.models import Notification
from .types import NotificationType


def _map(n):
    return NotificationType(
        id=str(n.id),
        type=n.notification_type,
        title=n.title,
        body=n.body,
        created_at=n.created_at,
        read=n.read,
        href=n.href or None,
        data=n.data,
    )


@strawberry.type
class NotificationQuery:
    @strawberry.field
    def notifications(
        self,
        info: strawberry.Info,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[NotificationType]:
        user = require_user(info)
        qs = Notification.objects.filter(user=user)
        if unread_only:
            qs = qs.filter(read_at__isnull=True)
        start = max(0, offset)
        end = start + max(1, min(limit, 100))
        return [_map(n) for n in qs[start:end]]

    @strawberry.field
    def unread_notification_count(self, info: strawberry.Info) -> int:
        return Notification.objects.filter(
            user=require_user(info), read_at__isnull=True
        ).count()
