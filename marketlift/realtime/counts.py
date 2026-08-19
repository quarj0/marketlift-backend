from __future__ import annotations

from django.db.models import F, Q

from messaging.models import Message
from notifications.models import Notification


def unread_message_count(user) -> int:
    if not user or not getattr(user, "is_authenticated", False):
        return 0

    viewer_scope = (
        Q(
            conversation__buyer=user,
            conversation__buyer_last_read_at__isnull=True,
        )
        | Q(
            conversation__buyer=user,
            created_at__gt=F("conversation__buyer_last_read_at"),
        )
        | Q(
            conversation__seller__user=user,
            conversation__seller_last_read_at__isnull=True,
        )
        | Q(
            conversation__seller__user=user,
            created_at__gt=F("conversation__seller_last_read_at"),
        )
    )

    return (
        Message.objects.filter(viewer_scope)
        .exclude(sender=user)
        .values("pk")
        .distinct()
        .count()
    )


def unread_notification_count(user) -> int:
    if not user or not getattr(user, "is_authenticated", False):
        return 0
    return Notification.objects.filter(user=user, read_at__isnull=True).count()
