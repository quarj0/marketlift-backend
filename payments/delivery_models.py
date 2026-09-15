from django.conf import settings
from django.db import models

from marketlift.common.models import UUIDTimeStampedModel


class DeliveryRider(UUIDTimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="delivery_rider",
    )
    active = models.BooleanField(default=True, db_index=True)
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ("user__full_name", "user__email")


class DeliveryAssignment(UUIDTimeStampedModel):
    class ConfirmationSource(models.TextChoices):
        RIDER_PIN = "rider_pin", "Rider PIN"
        BUYER_CONFIRMATION = "buyer_confirmation", "Buyer confirmation"
        ADMIN_OVERRIDE = "admin_override", "Administrator override"
        ADMIN_PIN = "admin_pin", "Administrator PIN"

    shipment = models.OneToOneField(
        "payments.Shipment",
        on_delete=models.PROTECT,
        related_name="delivery_assignment",
    )
    rider = models.ForeignKey(
        DeliveryRider,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="assignments",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    delivery_pin_ciphertext = models.TextField(blank=True)
    delivery_pin_failure_count = models.PositiveSmallIntegerField(default=0)
    delivery_pin_locked_until = models.DateTimeField(null=True, blank=True)
    delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    confirmation_source = models.CharField(
        max_length=32,
        choices=ConfirmationSource.choices,
        blank=True,
    )
    admin_override_reason = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("rider", "assigned_at"),
                name="delivery_assignment_rider_idx",
            ),
        ]


class DeliveryConfirmationAttempt(UUIDTimeStampedModel):
    assignment = models.ForeignKey(
        DeliveryAssignment,
        on_delete=models.PROTECT,
        related_name="confirmation_attempts",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    source = models.CharField(max_length=32)
    success = models.BooleanField(default=False, db_index=True)
    reason = models.CharField(max_length=120, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("assignment", "-created_at"),
                name="delivery_attempt_assignment_idx",
            ),
        ]
