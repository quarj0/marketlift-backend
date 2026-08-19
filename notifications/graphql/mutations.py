import strawberry
from django.core.exceptions import ValidationError
from graphql import GraphQLError

from marketlift.graphql.auth import require_user
from notifications.services import mark_all_notifications_read, mark_notification_read


@strawberry.type
class NotificationMutation:
    @strawberry.mutation
    def mark_notification_read(
        self, info: strawberry.Info, notification_id: strawberry.ID
    ) -> bool:
        user = require_user(info)
        try:
            mark_notification_read(user=user, notification_id=notification_id)
        except ValidationError as exc:
            raise GraphQLError("Notification not found.") from exc
        return True

    @strawberry.mutation
    def mark_all_notifications_read(self, info: strawberry.Info) -> int:
        return mark_all_notifications_read(user=require_user(info))
