from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from marketlift.common.models import UUIDTimeStampedModel


class ModerationCase(UUIDTimeStampedModel):
    class Status(models.TextChoices):
        REVIEW = "review", "Review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        REPORT = "report", "Report"
        AUTOMATED = "automated", "Automated"
        RISK = "risk", "Risk rule"
        CATEGORY = "category", "Category policy"

    listing = models.OneToOneField(
        "listings.Listing", on_delete=models.PROTECT, related_name="moderation_case"
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.REVIEW, db_index=True
    )
    source = models.CharField(
        max_length=16, choices=Source.choices, default=Source.MANUAL
    )
    review_reason = models.TextField()
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="opened_moderation_cases",
    )
    decision_reason = models.TextField(blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="decided_moderation_cases",
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    @property
    def final(self):
        return self.status in {self.Status.APPROVED, self.Status.REJECTED}

    def save(self, *args, **kwargs):
        if self.pk:
            old = ModerationCase.objects.filter(pk=self.pk).first()
            if old and old.final:
                raise ValidationError("A final moderation decision cannot be changed.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.listing_id}: {self.status}"
