import strawberry
from graphql import GraphQLError
from django.utils import timezone
from marketlift.graphql.auth import require_user
from notifications.models import Notification


@strawberry.type
class NotificationMutation:
    @strawberry.mutation
    def mark_notification_read(
        self, info: strawberry.Info, notification_id: strawberry.ID
    ) -> bool:
        user = require_user(info)
        try:
            n = Notification.objects.get(pk=str(notification_id), user=user)
        except (Notification.DoesNotExist, ValueError) as exc:
            raise GraphQLError("Notification not found.") from exc
        n.mark_read()
        return True

    @strawberry.mutation
    def mark_all_notifications_read(self, info: strawberry.Info) -> int:
        user = require_user(info)
        now = timezone.now()
        return Notification.objects.filter(user=user, read_at__isnull=True).update(
            read_at=now, updated_at=now
        )
