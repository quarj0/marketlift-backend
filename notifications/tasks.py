from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from .models import Notification


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


@shared_task
def deliver_pending_notification_emails():
    sent = 0
    for item in (
        Notification.objects.select_related("user")
        .filter(email_sent_at__isnull=True, delivery_attempts__lt=5)
        .order_by("created_at")[:200]
    ):
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
