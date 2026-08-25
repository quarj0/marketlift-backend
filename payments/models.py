from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from marketlift.common.models import UUIDTimeStampedModel
from marketlift.markets.defaults import default_market_country_code, default_market_currency


class Payment(UUIDTimeStampedModel):
    class Purpose(models.TextChoices):
        SUBSCRIPTION = "subscription", "Subscription"
        PROMOTION = "promotion", "Promotion"

    class Method(models.TextChoices):
        CARD = "card", "Card"
        MOBILE_MONEY = "mobile_money", "Mobile money"
        BANK_TRANSFER = "bank_transfer", "Bank transfer"
        USSD = "ussd", "USSD"
        EFT = "eft", "EFT"
        PIX = "pix", "Pix"
        BOLETO = "boleto", "Boleto"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments"
    )
    seller = models.ForeignKey(
        "sellers.SellerProfile", on_delete=models.PROTECT, related_name="payments"
    )
    purpose = models.CharField(max_length=16, choices=Purpose.choices)
    method = models.CharField(max_length=16, choices=Method.choices)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    country_code = models.CharField(max_length=2, default=default_market_country_code, db_index=True)
    currency = models.CharField(max_length=3, default=default_market_currency, editable=False)

    reference = models.CharField(max_length=64, unique=True)
    idempotency_key = models.CharField(max_length=80, unique=True)
    provider = models.CharField(max_length=40, default="mock")
    provider_order_id = models.CharField(max_length=100, blank=True, db_index=True)
    provider_payment_id = models.CharField(max_length=100, blank=True, db_index=True)
    provider_status = models.CharField(max_length=80, blank=True)
    provider_status_detail = models.CharField(max_length=120, blank=True)

    checkout_data = models.JSONField(default=dict, blank=True)
    failure_code = models.CharField(max_length=100, blank=True)
    failure_message = models.TextField(blank=True)

    seller_plan = models.ForeignKey(
        "subscriptions.SellerPlan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payments",
    )
    billing_cycle = models.CharField(max_length=12, blank=True)
    subscription = models.ForeignKey(
        "subscriptions.SellerSubscription",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )

    listing = models.ForeignKey(
        "listings.Listing",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payments",
    )
    promotion_product = models.ForeignKey(
        "promotions.PromotionProduct",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payments",
    )
    listing_promotion = models.ForeignKey(
        "promotions.ListingPromotion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )

    paid_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("status", "created_at")),
            models.Index(fields=("purpose", "status")),
            models.Index(fields=("seller", "created_at")),
        ]

    def __str__(self):
        return f"{self.reference} · {self.get_status_display()}"

    def clean(self):
        if self.amount < 0:
            raise ValidationError({"amount": "Amount cannot be negative."})
        if self.purpose == self.Purpose.SUBSCRIPTION:
            if not self.seller_plan_id or not self.billing_cycle:
                raise ValidationError(
                    "Subscription payments require a plan and billing cycle."
                )
            if self.listing_id or self.promotion_product_id:
                raise ValidationError(
                    "Subscription payments cannot reference a promotion."
                )
        elif self.purpose == self.Purpose.PROMOTION:
            if not self.listing_id or not self.promotion_product_id:
                raise ValidationError(
                    "Promotion payments require a listing and promotion product."
                )
            if self.seller_plan_id:
                raise ValidationError(
                    "Promotion payments cannot reference a seller plan."
                )
