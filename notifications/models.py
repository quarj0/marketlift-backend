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
