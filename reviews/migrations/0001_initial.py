from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sellers", "0001_initial"),
        ("listings", "0002_listingmedia_upload_alter_listingmedia_url"),
    ]
    operations = [
        migrations.CreateModel(
            name="SellerReview",
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
                    "rating",
                    models.PositiveSmallIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(5),
                        ]
                    ),
                ),
                ("comment", models.TextField(max_length=700)),
                ("seller_reply", models.TextField(blank=True, max_length=2000)),
                ("replied_at", models.DateTimeField(blank=True, null=True)),
                ("hidden_at", models.DateTimeField(blank=True, null=True)),
                ("hidden_reason", models.TextField(blank=True)),
                (
                    "listing",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reviews",
                        to="listings.listing",
                    ),
                ),
                (
                    "reviewer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="seller_reviews",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "seller",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reviews",
                        to="sellers.sellerprofile",
                    ),
                ),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddIndex(
            model_name="sellerreview",
            index=models.Index(
                fields=["seller", "hidden_at", "-created_at"],
                name="reviews_sel_hidden_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="sellerreview",
            index=models.Index(
                fields=["reviewer", "-created_at"], name="reviews_rev_created_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="sellerreview",
            constraint=models.UniqueConstraint(
                condition=models.Q(("listing__isnull", False)),
                fields=("reviewer", "listing"),
                name="reviews_one_per_reviewer_listing",
            ),
        ),
    ]
