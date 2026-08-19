import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from marketlift.common.models import UUIDTimeStampedModel


class Report(UUIDTimeStampedModel):
    class TargetType(models.TextChoices):
        LISTING = "listing", "Listing"
        SELLER = "seller", "Seller"
        USER = "user", "User"
        MESSAGE = "message", "Message"

    class Reason(models.TextChoices):
        ACCOUNT = "account", "Account"
        PAYMENT = "payment", "Payment"
        MODERATION = "moderation", "Moderation"
        SAFETY = "safety", "Safety"
        TECHNICAL = "technical", "Technical"
        OTHER = "other", "Other"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        REVIEW = "review", "Review"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Dismissed"

    reference = models.CharField(max_length=20, unique=True, editable=False)
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="submitted_reports",
    )
    target_type = models.CharField(max_length=16, choices=TargetType.choices)
    listing = models.ForeignKey(
        "listings.Listing",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reports",
    )
    seller = models.ForeignKey(
        "sellers.SellerProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reports",
    )
    user_target = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reports_received",
    )
    message = models.ForeignKey(
        "messaging.Message",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reports",
    )
    target_label_snapshot = models.CharField(max_length=240)
    reason = models.CharField(max_length=16, choices=Reason.choices)
    statement = models.TextField()
    priority = models.CharField(
        max_length=10, choices=Priority.choices, default=Priority.MEDIUM, db_index=True
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_reports",
    )
    internal_note = models.TextField(blank=True)
    decision_reason = models.TextField(blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="decided_reports",
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("status", "priority", "-created_at")),
            models.Index(fields=("target_type", "-created_at")),
        ]

    @property
    def final(self):
        return self.status in {self.Status.RESOLVED, self.Status.DISMISSED}

    @property
    def target_label(self):
        if self.listing_id:
            return self.listing.title
        if self.seller_id:
            return str(self.seller)
        if self.user_target_id:
            return self.user_target.full_name or self.user_target.email
        if self.message_id:
            return self.target_label_snapshot
        return self.target_label_snapshot

    def clean(self):
        mapping = {
            self.TargetType.LISTING: self.listing_id,
            self.TargetType.SELLER: self.seller_id,
            self.TargetType.USER: self.user_target_id,
            self.TargetType.MESSAGE: self.message_id,
        }
        if not mapping.get(self.target_type):
            raise ValidationError("The selected report target is required.")

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"RPT-{uuid.uuid4().hex[:8].upper()}"
        if self.pk:
            old = Report.objects.filter(pk=self.pk).first()
            if old and old.final:
                raise ValidationError("A final report decision cannot be changed.")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.reference
