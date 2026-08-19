from django.conf import settings
from django.db import models

from marketlift.common.models import UUIDTimeStampedModel


class SellerProfile(UUIDTimeStampedModel):
    class SellerType(models.TextChoices):
        INDIVIDUAL = "individual", "Individual"
        BUSINESS = "business", "Business"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="seller_profile",
    )
    seller_type = models.CharField(
        max_length=16,
        choices=SellerType.choices,
        default=SellerType.INDIVIDUAL,
    )
    display_name = models.CharField(max_length=160, blank=True)
    activated_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    is_suspended = models.BooleanField(default=False)
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspension_reason = models.TextField(blank=True)
    rating_average = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    review_count = models.PositiveIntegerField(default=0)
    positive_review_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0
    )

    class Meta:
        ordering = ("-activated_at",)

    def __str__(self) -> str:
        return self.display_name or self.user.full_name or self.user.email

    @property
    def verified(self) -> bool:
        return self.verified_at is not None


class SellerSettings(UUIDTimeStampedModel):
    user_profile = models.OneToOneField(
        SellerProfile, on_delete=models.CASCADE, related_name="settings"
    )
    new_inquiry = models.BooleanField(default=True)
    listing_status = models.BooleanField(default=True)
    performance = models.BooleanField(default=True)
    auto_renew = models.BooleanField(default=False)
    show_phone = models.BooleanField(default=True)
    vacation = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "seller settings"
