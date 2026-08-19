from accounts.models import User

from .models import Notification


def create_notification(
    *, user, notification_type: str, title: str, body: str, href: str = "", data=None
):
    return Notification.objects.create(
        user=user,
        notification_type=notification_type,
        title=title,
        body=body,
        href=href,
        data=data or {},
    )


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
    return len(rows)
