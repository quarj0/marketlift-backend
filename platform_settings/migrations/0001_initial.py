from django.db import migrations, models
import uuid


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="PlatformConfiguration",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "singleton_key",
                    models.CharField(
                        default="default", editable=False, max_length=20, unique=True
                    ),
                ),
                (
                    "marketplace_name",
                    models.CharField(default="Marketlift", max_length=100),
                ),
                (
                    "support_email",
                    models.EmailField(
                        default="support@marketlift.local", max_length=254
                    ),
                ),
                ("allow_new_registrations", models.BooleanField(default=True)),
                ("maintenance_mode", models.BooleanField(default=False)),
                ("automated_listing_flagging", models.BooleanField(default=True)),
                ("seller_verification_required", models.BooleanField(default=False)),
                (
                    "default_listing_duration_days",
                    models.PositiveIntegerField(default=90),
                ),
                ("max_listing_images", models.PositiveIntegerField(default=12)),
                ("high_risk_threshold", models.PositiveSmallIntegerField(default=70)),
                ("feature_flags", models.JSONField(blank=True, default=dict)),
            ],
        )
    ]
