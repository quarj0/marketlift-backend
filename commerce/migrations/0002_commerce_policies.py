import django.db.models.deletion
from django.db import migrations, models
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("commerce", "0001_initial"),
        ("categories", "0008_seed_complete_fipe_makes"),
        ("listings", "0011_listing_condition_catalog"),
    ]

    operations = [
        migrations.CreateModel(
            name="CategoryCommercePolicy",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("mode", models.CharField(choices=[("disabled", "Classified only"), ("optional", "Optional checkout"), ("enabled", "Checkout enabled")], db_index=True, default="disabled", max_length=12)),
                ("requires_verified_seller", models.BooleanField(default=True)),
                ("max_checkout_value_cents", models.PositiveBigIntegerField(blank=True, null=True)),
                ("shipping_allowed", models.BooleanField(default=False)),
                ("local_delivery_allowed", models.BooleanField(default=False)),
                ("pickup_allowed", models.BooleanField(default=True)),
                ("category", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="commerce_policy", to="categories.category")),
            ],
        ),
        migrations.CreateModel(
            name="ListingCommerceSettings",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("checkout_enabled", models.BooleanField(db_index=True, default=False)),
                ("stock_quantity", models.PositiveIntegerField(default=1)),
                ("shipping_enabled", models.BooleanField(default=False)),
                ("local_delivery_enabled", models.BooleanField(default=False)),
                ("pickup_enabled", models.BooleanField(default=True)),
                ("package_weight_grams", models.PositiveIntegerField(blank=True, null=True)),
                ("package_length_cm", models.PositiveIntegerField(blank=True, null=True)),
                ("package_width_cm", models.PositiveIntegerField(blank=True, null=True)),
                ("package_height_cm", models.PositiveIntegerField(blank=True, null=True)),
                ("listing", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="commerce_settings", to="listings.listing")),
            ],
        ),
    ]
