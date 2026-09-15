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
    from .services import push_enabled_for_notification

    return push_enabled_for_notification(item)


def _record_subscription_failure(
    subscription: WebPushSubscription, message: str, *, disable=False
):
    now = timezone.now()
    updates = {
        "failure_count": min(32767, subscription.failure_count + 1),
        "last_error": message[:1000],
        "updated_at": now,
    }
    if disable:
        updates["disabled_at"] = now
    WebPushSubscription.objects.filter(pk=subscription.pk).update(**updates)


def enqueue_web_push_delivery(delivery_id: str) -> bool:
    """Publish a durable delivery and record successful broker handoff."""
    try:
        deliver_web_push_delivery.delay(str(delivery_id))
    except Exception:
        # The delivery row intentionally remains recoverable with enqueued_at=NULL.
        return False
    now = timezone.now()
    WebPushDelivery.objects.filter(
        pk=delivery_id,
        sent_at__isnull=True,
    ).update(enqueued_at=now, updated_at=now)
    return True


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

    # This task already runs every minute from Celery Beat. Reuse that sweep to
    # recover push rows whose initial broker handoff failed, without requiring a
    # second independently configured periodic schedule.
    try:
        recover_pending_web_push_deliveries()
    except Exception:
        pass
    return sent


@shared_task
def fanout_web_push(notification_id: str) -> int:
    """Persist and enqueue one delivery per active browser subscription."""
    if not web_push_configured():
        return 0
    try:
        item = Notification.objects.select_related("user").get(pk=notification_id)
    except (Notification.DoesNotExist, ValueError):
        return 0

    from .services import prepare_web_push_deliveries

    delivery_ids = prepare_web_push_deliveries(item)
    return sum(1 for delivery_id in delivery_ids if enqueue_web_push_delivery(delivery_id))


@shared_task
def recover_pending_web_push_deliveries() -> int:
    """Recover rows whose initial Celery publication failed before handoff."""
    if not web_push_configured():
        return 0
    candidates = list(
        WebPushDelivery.objects.filter(
            sent_at__isnull=True,
            enqueued_at__isnull=True,
            attempts=0,
            subscription__disabled_at__isnull=True,
        )
        .order_by("created_at")
        .values_list("id", flat=True)[:200]
    )
    return sum(
        1 for delivery_id in candidates if enqueue_web_push_delivery(str(delivery_id))
    )


@shared_task(bind=True, max_retries=4)
def deliver_web_push_delivery(self, delivery_id: str):
    try:
        delivery = WebPushDelivery.objects.select_related(
            "notification__user",
            "subscription",
        ).get(pk=delivery_id)
    except (WebPushDelivery.DoesNotExist, ValueError):
        return "missing"

    if delivery.sent_at is not None:
        return "sent"
    if delivery.subscription.disabled_at is not None:
        return "disabled"
    if delivery.subscription.user_id != delivery.notification.user_id:
        # A browser endpoint may have been rebound to a different account after
        # this delivery was created. Never cross that account boundary.
        delivery.delete()
        return "owner-mismatch"
    if not _push_enabled(delivery.notification):
        return "preference-disabled"

    delivery.attempts = min(32767, delivery.attempts + 1)
    delivery.save(update_fields=("attempts", "updated_at"))

    try:
        send_web_push(
            subscription=delivery.subscription,
            notification=delivery.notification,
        )
    except WebPushHTTPError as exc:
        message = str(exc)[:1000]
        delivery.last_error = message
        delivery.save(update_fields=("last_error", "updated_at"))
        _record_subscription_failure(
            delivery.subscription,
            message,
            disable=exc.permanent_subscription_failure,
        )
        if exc.permanent_subscription_failure:
            return "subscription-gone"
        if exc.retryable:
            countdown = min(300, 10 * (2 ** self.request.retries))
            raise self.retry(exc=exc, countdown=countdown)
        return "rejected"
    except WebPushError as exc:
        message = str(exc)[:1000]
        delivery.last_error = message
        delivery.save(update_fields=("last_error", "updated_at"))
        _record_subscription_failure(delivery.subscription, message)
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
