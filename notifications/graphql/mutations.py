import strawberry
from django.core.exceptions import ValidationError

from marketlift.graphql.auth import require_user
from marketlift.graphql.errors import not_found_error, validation_error
from notifications.services import (
    mark_all_notifications_read,
    mark_notification_read,
    register_web_push_subscription,
    unregister_web_push_subscription,
)


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
            raise not_found_error(
                "Notification", code="NOTIFICATION_NOT_FOUND"
            ) from exc
        return True

    @strawberry.mutation
    def mark_all_notifications_read(self, info: strawberry.Info) -> int:
        return mark_all_notifications_read(user=require_user(info))

    @strawberry.mutation
    def register_web_push_subscription(
        self,
        info: strawberry.Info,
        endpoint: str,
        p256dh: str,
        auth: str,
    ) -> bool:
        user = require_user(info)
        request = getattr(info.context, "request", info.context)
        user_agent = ""
        if request is not None and hasattr(request, "META"):
            user_agent = request.META.get("HTTP_USER_AGENT", "")
        try:
            register_web_push_subscription(
                user=user,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                user_agent=user_agent,
            )
        except ValidationError as exc:
            raise validation_error(
                exc,
                code="WEB_PUSH_SUBSCRIPTION_VALIDATION_ERROR",
            ) from exc
        return True

    @strawberry.mutation
    def unregister_web_push_subscription(
        self,
        info: strawberry.Info,
        endpoint: str,
    ) -> bool:
        return unregister_web_push_subscription(
            user=require_user(info),
            endpoint=endpoint,
        )
