from __future__ import annotations

from hashlib import sha256

from accounts.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Notification, WebPushSubscription
from .web_push import validate_subscription_endpoint, validate_subscription_keys


def create_notification(
    *, user, notification_type: str, title: str, body: str, href: str = "", data=None
):
    item = Notification.objects.create(
        user=user,
        notification_type=notification_type,
        title=title,
        body=body,
        href=href,
        data=data or {},
    )
    notification_id = item.pk

    def _publish():
        from marketlift.realtime.events import publish_notification_created
        from notifications.tasks import fanout_web_push

        publish_notification_created(notification_id)
        fanout_web_push.delay(str(notification_id))

    transaction.on_commit(_publish, robust=True)
    return item


def mark_notification_read(*, user, notification_id):
    try:
        item = Notification.objects.get(pk=str(notification_id), user=user)
    except (Notification.DoesNotExist, ValueError) as exc:
        raise ValidationError("Notification not found.") from exc

    item.mark_read()
    item_id = item.pk
    user_id = user.pk

    def _publish():
        from marketlift.realtime.events import publish_notification_read

        publish_notification_read(item_id, user_id)

    transaction.on_commit(_publish, robust=True)
    return item


def mark_all_notifications_read(*, user) -> int:
    now = timezone.now()
    count = Notification.objects.filter(user=user, read_at__isnull=True).update(
        read_at=now, updated_at=now
    )
    user_id = user.pk

    def _publish():
        from marketlift.realtime.events import publish_notifications_read_all

        publish_notifications_read_all(user_id)

    transaction.on_commit(_publish, robust=True)
    return count


def register_web_push_subscription(
    *,
    user,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str = "",
) -> WebPushSubscription:
    try:
        endpoint = validate_subscription_endpoint(endpoint)
        p256dh, auth = validate_subscription_keys(p256dh=p256dh, auth=auth)
    except ValueError as exc:
        raise ValidationError({"subscription": str(exc)}) from exc

    digest = sha256(endpoint.encode("utf-8")).hexdigest()
    subscription, _ = WebPushSubscription.objects.update_or_create(
        endpoint_hash=digest,
        defaults={
            "user": user,
            "endpoint": endpoint,
            "p256dh": p256dh,
            "auth": auth,
            "user_agent": (user_agent or "")[:500],
            "disabled_at": None,
            "failure_count": 0,
            "last_error": "",
        },
    )
    return subscription


def unregister_web_push_subscription(*, user, endpoint: str) -> bool:
    endpoint = (endpoint or "").strip()
    if not endpoint:
        return False
    digest = sha256(endpoint.encode("utf-8")).hexdigest()
    now = timezone.now()
    updated = WebPushSubscription.objects.filter(
        endpoint_hash=digest,
        user=user,
        disabled_at__isnull=True,
    ).update(disabled_at=now, updated_at=now)
    return bool(updated)


def create_admin_notifications(
    *,
    notification_type: str,
    title: str,
    body: str,
    href: str = "",
    data=None,
    preference: str | None = None,
):
    """Fan out an operational notification to active staff accounts.

    `preference` is a PlatformConfiguration boolean field. Keeping preference
    evaluation here means payment/verification services do not need to know
    how administrators are stored or how notifications are delivered.
    """
    if preference:
        try:
            from platform_settings.models import PlatformConfiguration

            if not getattr(PlatformConfiguration.load(), preference):
                return 0
        except Exception:
            # Notification fan-out should not fail the domain operation if the
            # settings table is temporarily unavailable during startup/migrate.
            pass

    staff_ids = list(
        User.objects.filter(is_staff=True, is_active=True).values_list("id", flat=True)[
            :100
        ]
    )
    payload = dict(data or {})
    payload["adminOperational"] = True
    rows = [
        Notification(
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            body=body,
            href=href,
            data=payload,
        )
        for user_id in staff_ids
    ]
    if rows:
        Notification.objects.bulk_create(rows)
        notification_ids = [row.pk for row in rows if row.pk]

        def _publish():
            from marketlift.realtime.events import publish_notification_created
            from notifications.tasks import fanout_web_push

            for notification_id in notification_ids:
                publish_notification_created(notification_id)
                fanout_web_push.delay(str(notification_id))

        transaction.on_commit(_publish, robust=True)
    return len(rows)
