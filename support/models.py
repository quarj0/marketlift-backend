import uuid
from django.conf import settings
from django.db import models
from marketlift.common.models import UUIDTimeStampedModel


class SupportTicket(UUIDTimeStampedModel):
    class Category(models.TextChoices):
        ACCOUNT = "account", "Account"
        PAYMENT = "payment", "Payment"
        LISTING = "listing", "Listing"
        VERIFICATION = "verification", "Verification"
        SAFETY = "safety", "Safety"
        TECHNICAL = "technical", "Technical"
        OTHER = "other", "Other"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        REVIEW = "review", "In review"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    reference = models.CharField(max_length=20, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="support_tickets",
    )
    subject = models.CharField(max_length=180)
    category = models.CharField(
        max_length=20, choices=Category.choices, default=Category.OTHER
    )
    priority = models.CharField(
        max_length=12, choices=Priority.choices, default=Priority.MEDIUM, db_index=True
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_support_tickets",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    last_customer_message_at = models.DateTimeField(null=True, blank=True)
    last_staff_message_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-updated_at",)
        indexes = [
            models.Index(
                fields=("status", "priority", "-updated_at"),
                name="support_status_prio_idx",
            ),
            models.Index(
                fields=("user", "-updated_at"), name="support_user_updated_idx"
            ),
        ]

    def save(self, *a, **kw):
        if not self.reference:
            self.reference = f"SUP-{uuid.uuid4().hex[:8].upper()}"
        super().save(*a, **kw)

    def __str__(self):
        return self.reference


class SupportMessage(UUIDTimeStampedModel):
    ticket = models.ForeignKey(
        SupportTicket, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="support_messages",
    )
    body = models.TextField(max_length=5000)
    internal = models.BooleanField(default=False)
    upload = models.ForeignKey(
        "uploads.UploadAsset",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="support_messages",
    )

    class Meta:
        ordering = ("created_at",)
        indexes = [
            models.Index(fields=("ticket", "created_at"), name="support_msg_ticket_idx")
        ]
