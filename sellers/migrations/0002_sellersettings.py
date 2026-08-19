from django.db import migrations, models
import django.db.models.deletion, uuid


class Migration(migrations.Migration):
    dependencies = [("sellers", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="SellerSettings",
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
                ("new_inquiry", models.BooleanField(default=True)),
                ("listing_status", models.BooleanField(default=True)),
                ("performance", models.BooleanField(default=True)),
                ("auto_renew", models.BooleanField(default=False)),
                ("show_phone", models.BooleanField(default=True)),
                ("vacation", models.BooleanField(default=False)),
                (
                    "user_profile",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="settings",
                        to="sellers.sellerprofile",
                    ),
                ),
            ],
            options={"verbose_name_plural": "seller settings"},
        )
    ]
