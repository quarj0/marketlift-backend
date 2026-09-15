from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .models import Notification, WebPushDelivery, WebPushSubscription
from .web_push import WebPushError, WebPushHTTPError, send_web_push, web_push_configured


def _email_enabled(item):
    if item.user.is_staff and (item.data or {}).get("adminOperational"):
        try:
            from platform_settings.models import PlatformConfiguration

            if not PlatformConfiguration.load().admin_email_operational_alerts:
                return False
        except Exception:
            pass
    try:
        s = item.user.settings
    except Exception:
        return True
    if item.notification_type == "message":
        return s.email_messages
    if item.notification_type in {"listing", "moderation", "seller"}:
        return s.email_listing_updates
    if item.notification_type in {"recommendation", "saved_search"}:
        return s.email_recommendations
    if item.notification_type == "marketing":
        return s.marketing_emails
    return True


def _push_enabled(item):
    # Admin operational alerts belong to the administrator console, which does
    # not register marketplace PWA subscriptions.
    if (item.data or {}).get("adminOperational"):
        return False
    try:
        account_settings = item.user.settings
    except Exception:
        return False
    if item.notification_type == "message":
        return account_settings.push_messages
    if item.notification_type in {"listing", "moderation", "seller"}:
        return account_settings.push_listing_updates
    return False


@shared_task
def deliver_pending_notification_emails():
    sent = 0
    candidates = list(
        Notification.objects.filter(email_sent_at__isnull=True, delivery_attempts__lt=5)
        .order_by("created_at")
        .values_list("id", flat=True)[:200]
    )
    for candidate in candidates:
        with transaction.atomic():
            # Concurrent workers skip a notification while its bounded send is in progress.
            item = (
                Notification.objects.select_for_update(skip_locked=True, of=("self",))
                .select_related("user", "user__settings")
                .filter(
                    pk=candidate, email_sent_at__isnull=True, delivery_attempts__lt=5
                )
                .first()
            )
            if item is None:
                continue
            if not _email_enabled(item):
                item.email_sent_at = timezone.now()
                item.save(update_fields=("email_sent_at", "updated_at"))
                continue
            item.delivery_attempts += 1
            try:
                send_mail(
                    item.title,
                    item.body,
                    settings.DEFAULT_FROM_EMAIL,
                    [item.user.email],
                    fail_silently=False,
                )
                item.email_sent_at = timezone.now()
                item.last_delivery_error = ""
                sent += 1
            except Exception as exc:
                item.last_delivery_error = str(exc)[:1000]
            item.save(
                update_fields=(
                    "delivery_attempts",
                    "email_sent_at",
                    "last_delivery_error",
                    "updated_at",
                )
            )
    return sent


@shared_task
def fanout_web_push(notification_id: str) -> int:
    """Create one durable delivery per active browser subscription."""

    if not web_push_configured():
        return 0
    try:
        item = Notification.objects.select_related("user", "user__settings").get(
            pk=notification_id
        )
    except (Notification.DoesNotExist, ValueError):
        return 0
    if not _push_enabled(item):
        return 0

    subscriptions = WebPushSubscription.objects.filter(
        user=item.user,
        disabled_at__isnull=True,
    )
    queued = 0
    for subscription in subscriptions.iterator():
        delivery, _ = WebPushDelivery.objects.get_or_create(
            notification=item,
            subscription=subscription,
        )
        if delivery.sent_at is not None:
            continue
        deliver_web_push_delivery.delay(str(delivery.id))
        queued += 1
    return queued


@shared_task(bind=True, max_retries=4)
def deliver_web_push_delivery(self, delivery_id: str):
    try:
        delivery = WebPushDelivery.objects.select_related(
            "notification__user",
            "notification__user__settings",
            "subscription",
        ).get(pk=delivery_id)
    except (WebPushDelivery.DoesNotExist, ValueError):
        return "missing"

    if delivery.sent_at is not None:
        return "sent"
    if delivery.subscription.disabled_at is not None:
        return "disabled"
    if not _push_enabled(delivery.notification):
        return "preference-disabled"

    delivery.attempts = min(65535, delivery.attempts + 1)
    delivery.save(update_fields=("attempts", "updated_at"))

    try:
        send_web_push(
            subscription=delivery.subscription,
            notification=delivery.notification,
        )
    except WebPushHTTPError as exc:
        delivery.last_error = str(exc)[:1000]
        delivery.save(update_fields=("last_error", "updated_at"))
        if exc.permanent_subscription_failure:
            now = timezone.now()
            WebPushSubscription.objects.filter(
                pk=delivery.subscription_id,
                disabled_at__isnull=True,
            ).update(
                disabled_at=now,
                failure_count=delivery.subscription.failure_count + 1,
                last_error=str(exc)[:1000],
                updated_at=now,
            )
            return "subscription-gone"
        if exc.retryable:
            countdown = min(300, 10 * (2 ** self.request.retries))
            raise self.retry(exc=exc, countdown=countdown)
        return "rejected"
    except WebPushError as exc:
        delivery.last_error = str(exc)[:1000]
        delivery.save(update_fields=("last_error", "updated_at"))
        countdown = min(300, 10 * (2 ** self.request.retries))
        raise self.retry(exc=exc, countdown=countdown)

    now = timezone.now()
    delivery.sent_at = now
    delivery.last_error = ""
    delivery.save(update_fields=("sent_at", "last_error", "updated_at"))
    WebPushSubscription.objects.filter(pk=delivery.subscription_id).update(
        last_success_at=now,
        failure_count=0,
        last_error="",
        updated_at=now,
    )
    return "sent"
