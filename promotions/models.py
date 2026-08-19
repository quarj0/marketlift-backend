from django.db import models
from django.utils import timezone

from marketlift.common.models import UUIDTimeStampedModel


class PromotionProduct(UUIDTimeStampedModel):
    class Code(models.TextChoices):
        FEATURED = "featured", "Featured"
        TOP_SEARCH = "top_search", "Top of Search"
        URGENT = "urgent", "Urgent"
        HOMEPAGE = "homepage", "Homepage Featured"

    code = models.CharField(max_length=24, choices=Code.choices, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    duration_days = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=12, decimal_places=2)
    active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "price")

    def __str__(self) -> str:
        return self.name


class ListingPromotion(UUIDTimeStampedModel):
    class Source(models.TextChoices):
        PURCHASE = "purchase", "Purchase"
        PLAN_CREDIT = "plan_credit", "Plan credit"
        ADMIN = "admin", "Admin"

    listing = models.ForeignKey(
        "listings.Listing",
        on_delete=models.CASCADE,
        related_name="promotions",
    )
    product = models.ForeignKey(
        PromotionProduct,
        on_delete=models.PROTECT,
        related_name="activations",
    )
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.PURCHASE)
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField()
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-starts_at",)
        indexes = [
            models.Index(fields=("listing", "starts_at", "ends_at")),
            models.Index(fields=("product", "starts_at", "ends_at")),
        ]

    @property
    def is_active(self) -> bool:
        now = timezone.now()
        return self.cancelled_at is None and self.starts_at <= now < self.ends_at

    def __str__(self) -> str:
        return f"{self.listing} · {self.product.name}"
