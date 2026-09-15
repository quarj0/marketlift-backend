from django.conf import settings
from django.db import models
from django.utils import timezone
from marketlift.common.models import UUIDTimeStampedModel


class Notification(UUIDTimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    notification_type = models.CharField(max_length=32, db_index=True)
    title = models.CharField(max_length=180)
    body = models.TextField()
    href = models.CharField(max_length=500, blank=True)
    data = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)
    email_sent_at = models.DateTimeField(null=True, blank=True, db_index=True)
    delivery_attempts = models.PositiveSmallIntegerField(default=0)
    last_delivery_error = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("user", "read_at", "-created_at"))]

    @property
    def read(self):
        return self.read_at is not None

    def mark_read(self):
        if self.read_at is None:
            self.read_at = timezone.now()
            self.save(update_fields=("read_at", "updated_at"))
        return self


class WebPushSubscription(UUIDTimeStampedModel):
    """One browser/PWA Push API subscription owned by a Marketlift account.

    The endpoint itself contains a bearer-like opaque token, so uniqueness is
    enforced with a SHA-256 digest rather than indexing the endpoint text.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="web_push_subscriptions",
    )
    endpoint_hash = models.CharField(max_length=64, unique=True)
    endpoint = models.TextField()
    p256dh = models.CharField(max_length=192)
    auth = models.CharField(max_length=96)
    user_agent = models.CharField(max_length=500, blank=True)
    disabled_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    failure_count = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ("-updated_at",)
        indexes = [
            models.Index(
                fields=("user", "disabled_at", "-updated_at"),
                name="notif_push_user_active_idx",
            )
        ]

    @property
    def active(self):
        return self.disabled_at is None


class WebPushDelivery(UUIDTimeStampedModel):
    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name="web_push_deliveries",
    )
    subscription = models.ForeignKey(
        WebPushSubscription,
        on_delete=models.CASCADE,
        related_name="deliveries",
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_error = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("notification", "subscription"),
                name="notif_push_delivery_unique",
            )
        ]
        indexes = [
            models.Index(
                fields=("sent_at", "created_at"),
                name="notif_push_pending_idx",
            )
        ]
