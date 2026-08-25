from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from marketlift.common.models import UUIDTimeStampedModel


class VerificationSubmission(UUIDTimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        REVIEW = "review", "Under review"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"

    class RiskLevel(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    class DocumentType(models.TextChoices):
        NATIONAL_ID = "national_id", "National ID"
        DRIVERS_LICENCE = "drivers_licence", "Driver's licence"
        PASSPORT = "passport", "Passport"

    seller = models.ForeignKey(
        "sellers.SellerProfile",
        on_delete=models.CASCADE,
        related_name="verification_submissions",
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )

    # Identity numbers are deliberately never stored in plaintext. These generic
    # fields are the canonical multi-market representation. The legacy CPF fields
    # remain as compatibility mirrors for Brazil until the old frontend is retired.
    identity_country_code = models.CharField(max_length=2, blank=True, db_index=True)
    identity_type = models.CharField(max_length=40, blank=True)
    identity_digest = models.CharField(max_length=64, blank=True, db_index=True)
    identity_masked = models.CharField(max_length=40, blank=True)
    cpf_digest = models.CharField(max_length=64, blank=True, default="", db_index=True)
    cpf_masked = models.CharField(max_length=14, blank=True, default="")
    legal_name = models.CharField(max_length=160)
    birth_date = models.DateField()
    document_type = models.CharField(
        max_length=24, choices=DocumentType.choices, blank=True
    )
    document_front_url = models.URLField(blank=True)
    document_back_url = models.URLField(blank=True)
    selfie_url = models.URLField(blank=True)

    provider = models.CharField(max_length=80, blank=True)
    provider_reference = models.CharField(max_length=160, blank=True, db_index=True)
    provider_result = models.TextField(blank=True)
    automated_checks = models.JSONField(default=dict, blank=True)
    risk_flags = models.JSONField(default=list, blank=True)
    risk_level = models.CharField(
        max_length=12, choices=RiskLevel.choices, default=RiskLevel.LOW
    )

    submitted_at = models.DateTimeField(auto_now_add=True)
    review_started_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verification_decisions",
    )
    decision_note = models.TextField(blank=True)

    class Meta:
        ordering = ("-submitted_at",)
        indexes = [
            models.Index(fields=("status", "submitted_at")),
            models.Index(fields=("seller", "status")),
            models.Index(fields=("risk_level", "status")),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("seller",),
                condition=models.Q(status__in=("pending", "review")),
                name="verifications_one_open_per_seller",
            )
        ]

    def __str__(self):
        return f"{self.seller} · {self.get_status_display()}"

    @property
    def is_final(self):
        return self.status in {self.Status.VERIFIED, self.Status.REJECTED}

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values("status").first()
            if previous and previous["status"] in {
                self.Status.VERIFIED,
                self.Status.REJECTED,
            }:
                if self.status != previous["status"]:
                    raise ValidationError(
                        "A final verification decision cannot be changed."
                    )
        super().save(*args, **kwargs)
