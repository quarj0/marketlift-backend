from django.db import models
from django.db.models import Q

from marketlift.common.models import UUIDTimeStampedModel


class SellerPlan(UUIDTimeStampedModel):
    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    monthly_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    yearly_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    listing_limit = models.PositiveIntegerField(default=5)
    promotion_credits = models.PositiveIntegerField(default=0)
    features = models.JSONField(default=list, blank=True)
    visibility_weight = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    recommended = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "monthly_price", "name")

    def __str__(self) -> str:
        return self.name


class SellerSubscription(UUIDTimeStampedModel):
    class BillingCycle(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        YEARLY = "yearly", "Yearly"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past due"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    seller = models.ForeignKey(
        "sellers.SellerProfile",
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    plan = models.ForeignKey(
        SellerPlan,
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    billing_cycle = models.CharField(
        max_length=12,
        choices=BillingCycle.choices,
        default=BillingCycle.MONTHLY,
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ACTIVE
    )
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("seller",),
                condition=Q(status="active"),
                name="subscriptions_one_active_per_seller",
            )
        ]

    def __str__(self) -> str:
        return f"{self.seller} · {self.plan.name} ({self.status})"
