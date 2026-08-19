from django.db import models

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
