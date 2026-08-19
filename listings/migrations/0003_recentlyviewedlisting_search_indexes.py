from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion, uuid


class Migration(migrations.Migration):
    dependencies = [
        ("listings", "0002_listingmedia_upload_alter_listingmedia_url"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="RecentlyViewedListing",
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
                    "listing",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="recent_viewers",
                        to="listings.listing",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="recently_viewed_listings",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("-updated_at",)},
        ),
        migrations.AddConstraint(
            model_name="recentlyviewedlisting",
            constraint=models.UniqueConstraint(
                fields=("user", "listing"), name="listings_unique_recent_view"
            ),
        ),
        migrations.AddIndex(
            model_name="recentlyviewedlisting",
            index=models.Index(
                fields=["user", "-updated_at"], name="listings_recent_user_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="listing",
            index=models.Index(
                fields=["status", "published_at"], name="listings_status_pub_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="listing",
            index=models.Index(
                fields=["state_code", "status", "-created_at"],
                name="listings_state_status_idx",
            ),
        ),
    ]
