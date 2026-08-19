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
