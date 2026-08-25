from django.core.exceptions import ValidationError
from django.db import models, transaction

from marketlift.common.models import UUIDTimeStampedModel


class PlatformConfiguration(UUIDTimeStampedModel):
    singleton_key = models.CharField(
        max_length=20, unique=True, default="default", editable=False
    )

    marketplace_name = models.CharField(max_length=100, default="Marketlift")
    support_email = models.EmailField(default="support@marketlift.local")

    allow_new_registrations = models.BooleanField(default=True)
    allow_seller_activation = models.BooleanField(default=True)
    maintenance_mode = models.BooleanField(default=False)

    automated_listing_flagging = models.BooleanField(default=True)
    seller_verification_required = models.BooleanField(default=False)
    default_listing_duration_days = models.PositiveIntegerField(default=90)
    max_listing_images = models.PositiveIntegerField(default=12)
    high_risk_threshold = models.PositiveSmallIntegerField(default=70)

    admin_email_operational_alerts = models.BooleanField(default=True)
    admin_verification_queue_alerts = models.BooleanField(default=True)
    admin_payment_failure_alerts = models.BooleanField(default=True)

    feature_flags = models.JSONField(default=dict, blank=True)

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(singleton_key="default")[0]

    def __str__(self) -> str:
        return self.marketplace_name


class Market(UUIDTimeStampedModel):
    """Admin-managed commercial market configuration.

    Country definitions remain in ``marketlift.markets.profiles`` as safe code
    defaults. This model controls which of those markets are actually available
    to users and allows business configuration to change without a deployment.
    Provider secrets remain environment/secret-store values.
    """

    code = models.CharField(max_length=2, unique=True, db_index=True)
    country_name = models.CharField(max_length=100)
    locale = models.CharField(max_length=20)
    django_language_code = models.CharField(max_length=20)
    currency = models.CharField(max_length=3)
    currency_symbol = models.CharField(max_length=12)
    timezone = models.CharField(max_length=64)
    geocoder_language = models.CharField(max_length=80, blank=True)

    payment_provider = models.CharField(max_length=40, default="disabled")
    payment_methods = models.JSONField(default=list, blank=True)
    identity_provider = models.CharField(max_length=40, default="disabled")
    identity_label = models.CharField(max_length=100)
    identity_key = models.CharField(max_length=40)

    currency_aliases = models.JSONField(default=list, blank=True)
    currency_subunit_factor = models.PositiveIntegerField(default=100)
    hierarchical_location_catalog = models.BooleanField(default=False)

    is_enabled = models.BooleanField(default=False, db_index=True)
    is_default = models.BooleanField(default=False, db_index=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "country_name")

    def clean(self):
        super().clean()
        self.code = (self.code or "").strip().upper()
        self.currency = (self.currency or "").strip().upper()
        self.payment_provider = (self.payment_provider or "disabled").strip().lower()
        self.identity_provider = (self.identity_provider or "disabled").strip().lower()
        if len(self.code) != 2:
            raise ValidationError(
                {"code": "Market code must be a 2-letter country code."}
            )
        try:
            from marketlift.markets.profiles import get_market_profile

            get_market_profile(self.code)
        except ValueError as exc:
            raise ValidationError({"code": str(exc)}) from exc
        if len(self.currency) != 3:
            raise ValidationError({"currency": "Currency must be a 3-letter ISO code."})
        if self.is_default and not self.is_enabled:
            raise ValidationError({"is_default": "The default market must be enabled."})
        if not isinstance(self.payment_methods, list):
            raise ValidationError(
                {"payment_methods": "Payment methods must be a list."}
            )
        if self.currency_subunit_factor < 1:
            raise ValidationError(
                {"currency_subunit_factor": "Subunit factor must be positive."}
            )

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()
        self.currency = (self.currency or "").strip().upper()
        with transaction.atomic():
            if self.is_default:
                # Serialize default-market changes so two admins cannot leave
                # more than one market default during concurrent updates.
                list(
                    type(self).objects.select_for_update().values_list("pk", flat=True)
                )
                type(self).objects.exclude(pk=self.pk).filter(is_default=True).update(
                    is_default=False
                )
            result = super().save(*args, **kwargs)
            transaction.on_commit(self._invalidate_runtime_cache)
            return result

    @staticmethod
    def _invalidate_runtime_cache():
        from marketlift.markets.service import invalidate_market_cache

        invalidate_market_cache()

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            result = super().delete(*args, **kwargs)
            transaction.on_commit(self._invalidate_runtime_cache)
            return result

    def __str__(self) -> str:
        state = "enabled" if self.is_enabled else "disabled"
        return f"{self.country_name} ({self.code}) · {state}"


class SellerPlanMarketPrice(UUIDTimeStampedModel):
    market = models.ForeignKey(
        Market, on_delete=models.CASCADE, related_name="seller_plan_prices"
    )
    plan = models.ForeignKey(
        "subscriptions.SellerPlan",
        on_delete=models.CASCADE,
        related_name="market_prices",
    )
    monthly_price = models.DecimalField(max_digits=12, decimal_places=2)
    yearly_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ("market__sort_order", "plan__sort_order", "plan__name")
        constraints = [
            models.UniqueConstraint(
                fields=("market", "plan"),
                name="platform_settings_unique_plan_market_price",
            )
        ]

    def clean(self):
        super().clean()
        if self.monthly_price < 0 or self.yearly_price < 0:
            raise ValidationError("Market prices cannot be negative.")

    def __str__(self) -> str:
        return f"{self.market.code} · {self.plan.code}"


class PromotionProductMarketPrice(UUIDTimeStampedModel):
    market = models.ForeignKey(
        Market, on_delete=models.CASCADE, related_name="promotion_prices"
    )
    product = models.ForeignKey(
        "promotions.PromotionProduct",
        on_delete=models.CASCADE,
        related_name="market_prices",
    )
    price = models.DecimalField(max_digits=12, decimal_places=2)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ("market__sort_order", "product__sort_order", "product__name")
        constraints = [
            models.UniqueConstraint(
                fields=("market", "product"),
                name="platform_settings_unique_promotion_market_price",
            )
        ]

    def clean(self):
        super().clean()
        if self.price < 0:
            raise ValidationError("Market prices cannot be negative.")

    def __str__(self) -> str:
        return f"{self.market.code} · {self.product.code}"
