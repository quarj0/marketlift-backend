from __future__ import annotations

from hashlib import sha256

from accounts.models import User
from accounts.services import get_account_settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Notification, WebPushDelivery, WebPushSubscription
from .web_push import (
    validate_subscription_endpoint,
    validate_subscription_keys,
    web_push_configured,
)


def _safe_href(value: str, *, fallback: str = "/notifications") -> str:
    value = (value or "").strip()
    if not value:
        return ""
    # Notification destinations are application routes, never arbitrary links.
    # This protects service-worker/page click handlers even if a future caller
    # accidentally passes an absolute or protocol-relative URL.
    if not value.startswith("/") or value.startswith("//"):
        return fallback
    return value[:500]


def push_enabled_for_notification(item: Notification) -> bool:
    # Admin operational alerts belong to the administrator console, which does
    # not register marketplace PWA subscriptions.
    if (item.data or {}).get("adminOperational"):
        return False
    account_settings = get_account_settings(item.user)
    if item.notification_type == "message":
        return account_settings.push_messages
    if item.notification_type in {"listing", "moderation", "seller"}:
        return account_settings.push_listing_updates
    return False


def prepare_web_push_deliveries(item: Notification) -> list[str]:
    """Persist recoverable delivery rows before any broker publication."""
    if not web_push_configured() or not push_enabled_for_notification(item):
        return []

    delivery_ids: list[str] = []
    subscriptions = WebPushSubscription.objects.filter(
        user=item.user,
        disabled_at__isnull=True,
    )
    for subscription in subscriptions.iterator():
        delivery, _ = WebPushDelivery.objects.get_or_create(
            notification=item,
            subscription=subscription,
        )
        if delivery.sent_at is None:
            delivery_ids.append(str(delivery.id))
    return delivery_ids


def create_notification(
    *, user, notification_type: str, title: str, body: str, href: str = "", data=None
):
    item = Notification.objects.create(
        user=user,
        notification_type=notification_type,
        title=title,
        body=body,
        href=_safe_href(href),
        data=data or {},
    )
    notification_id = item.pk
    delivery_ids = prepare_web_push_deliveries(item)

    def _publish_realtime():
        from marketlift.realtime.events import publish_notification_created

        publish_notification_created(notification_id)

    def _enqueue_web_push():
        from notifications.tasks import enqueue_web_push_delivery

        for delivery_id in delivery_ids:
            enqueue_web_push_delivery(delivery_id)

    transaction.on_commit(_publish_realtime, robust=True)
    transaction.on_commit(_enqueue_web_push, robust=True)
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


@transaction.atomic
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
    subscription = (
        WebPushSubscription.objects.select_for_update()
        .filter(endpoint_hash=digest)
        .first()
    )
    if subscription is None:
        return WebPushSubscription.objects.create(
            user=user,
            endpoint_hash=digest,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=(user_agent or "")[:500],
        )

    if subscription.user_id != user.pk:
        # A Push API endpoint is browser-scoped and can survive account changes.
        # Never let pending notifications from the previous account follow it.
        WebPushDelivery.objects.filter(
            subscription=subscription,
            sent_at__isnull=True,
        ).delete()

    subscription.user = user
    subscription.endpoint = endpoint
    subscription.p256dh = p256dh
    subscription.auth = auth
    subscription.user_agent = (user_agent or "")[:500]
    subscription.disabled_at = None
    subscription.failure_count = 0
    subscription.last_error = ""
    subscription.save(
        update_fields=(
            "user",
            "endpoint",
            "p256dh",
            "auth",
            "user_agent",
            "disabled_at",
            "failure_count",
            "last_error",
            "updated_at",
        )
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
    """Fan out an operational notification to active staff accounts."""
    if preference:
        try:
            from platform_settings.models import PlatformConfiguration

            if not getattr(PlatformConfiguration.load(), preference):
                return 0
        except Exception:
            pass

    staff_ids = list(
        User.objects.filter(is_staff=True, is_active=True).values_list("id", flat=True)[
            :100
        ]
    )
    payload = dict(data or {})
    payload["adminOperational"] = True
    safe_href = _safe_href(href)
    rows = [
        Notification(
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            body=body,
            href=safe_href,
            data=payload,
        )
        for user_id in staff_ids
    ]
    if rows:
        Notification.objects.bulk_create(rows)
        notification_ids = [row.pk for row in rows if row.pk]

        def _publish_realtime():
            from marketlift.realtime.events import publish_notification_created

            for notification_id in notification_ids:
                publish_notification_created(notification_id)

        transaction.on_commit(_publish_realtime, robust=True)
    return len(rows)
