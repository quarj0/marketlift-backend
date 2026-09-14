from django.db import models

from marketlift.common.models import UUIDTimeStampedModel


class CategoryCommercePolicy(UUIDTimeStampedModel):
    class Mode(models.TextChoices):
        DISABLED = "disabled", "Classified only"
        OPTIONAL = "optional", "Optional checkout"
        ENABLED = "enabled", "Checkout enabled"

    category = models.OneToOneField(
        "categories.Category", on_delete=models.CASCADE, related_name="commerce_policy"
    )
    mode = models.CharField(
        max_length=12, choices=Mode.choices, default=Mode.DISABLED, db_index=True
    )
    requires_verified_seller = models.BooleanField(default=True)
    max_checkout_value_cents = models.PositiveBigIntegerField(null=True, blank=True)
    shipping_allowed = models.BooleanField(default=False)
    local_delivery_allowed = models.BooleanField(default=False)
    pickup_allowed = models.BooleanField(default=True)

    class Meta:
        app_label = "commerce"


class ListingCommerceSettings(UUIDTimeStampedModel):
    listing = models.OneToOneField(
        "listings.Listing", on_delete=models.CASCADE, related_name="commerce_settings"
    )
    checkout_enabled = models.BooleanField(default=False, db_index=True)
    stock_quantity = models.PositiveIntegerField(default=1)
    shipping_enabled = models.BooleanField(default=False)
    local_delivery_enabled = models.BooleanField(default=False)
    pickup_enabled = models.BooleanField(default=True)
    package_weight_grams = models.PositiveIntegerField(null=True, blank=True)
    package_length_cm = models.PositiveIntegerField(null=True, blank=True)
    package_width_cm = models.PositiveIntegerField(null=True, blank=True)
    package_height_cm = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        app_label = "commerce"
