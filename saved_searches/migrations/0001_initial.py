from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion, uuid


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("listings", "0002_listingmedia_upload_alter_listingmedia_url"),
    ]
    operations = [
        migrations.CreateModel(
            name="SavedSearch",
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
                ("name", models.CharField(blank=True, max_length=120)),
                ("criteria", models.JSONField(default=dict)),
                ("alerts_enabled", models.BooleanField(default=True)),
                ("active", models.BooleanField(default=True)),
                ("last_checked_at", models.DateTimeField(blank=True, null=True)),
                ("last_notified_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="saved_searches",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="SavedSearchMatch",
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
                ("notified_at", models.DateTimeField(blank=True, null=True)),
                (
                    "listing",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="saved_search_matches",
                        to="listings.listing",
                    ),
                ),
                (
                    "saved_search",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="matches",
                        to="saved_searches.savedsearch",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="savedsearch",
            index=models.Index(
                fields=["user", "active", "-created_at"],
                name="savedsearch_user_active_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="savedsearch",
            index=models.Index(
                fields=["alerts_enabled", "active", "last_checked_at"],
                name="savedsearch_alert_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="savedsearchmatch",
            constraint=models.UniqueConstraint(
                fields=("saved_search", "listing"), name="saved_searches_unique_match"
            ),
        ),
        migrations.AddIndex(
            model_name="savedsearchmatch",
            index=models.Index(
                fields=["saved_search", "notified_at"],
                name="savedsearch_match_notif_idx",
            ),
        ),
    ]
