from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from accounts.services import get_account_settings
from notifications.models import WebPushSubscription
from notifications.services import create_notification
from notifications.web_push import web_push_configured


class Command(BaseCommand):
    help = "Create a real test notification for one Marketlift account."

    def add_arguments(self, parser):
        parser.add_argument("email", help="Email address of the receiving Marketlift account.")

    def handle(self, *args, **options):
        email = str(options["email"]).strip().lower()
        try:
            user = User.objects.get(email__iexact=email, is_active=True)
        except User.DoesNotExist as exc:
            raise CommandError("No active Marketlift account matches that email.") from exc

        preferences = get_account_settings(user)
        active_push = WebPushSubscription.objects.filter(
            user=user,
            disabled_at__isnull=True,
        ).count()
        email_configured = bool(settings.ANYMAIL.get("RESEND_API_KEY"))

        self.stdout.write(
            self.style.NOTICE(
                "Channels: "
                f"emailConfigured={email_configured}, "
                f"emailMessages={preferences.email_messages}, "
                f"webPushConfigured={web_push_configured()}, "
                f"pushMessages={preferences.push_messages}, "
                f"activePushSubscriptions={active_push}"
            )
        )

        notification = create_notification(
            user=user,
            notification_type="message",
            title="Marketlift notification test",
            body="If you received this by email or browser notification, this channel is working.",
            href="/notifications",
            data={"deliveryTest": True},
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Created notification {notification.id}. "
                "Email and Web Push delivery were queued according to the account preferences."
            )
        )
