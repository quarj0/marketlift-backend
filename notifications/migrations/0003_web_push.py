from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("notifications", "0002_delivery_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="WebPushSubscription",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=__import__("uuid").uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("endpoint_hash", models.CharField(max_length=64, unique=True)),
                ("endpoint", models.TextField()),
                ("p256dh", models.CharField(max_length=192)),
                ("auth", models.CharField(max_length=96)),
                ("user_agent", models.CharField(blank=True, max_length=500)),
                (
                    "disabled_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                ("last_success_at", models.DateTimeField(blank=True, null=True)),
                ("failure_count", models.PositiveSmallIntegerField(default=0)),
                ("last_error", models.TextField(blank=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="web_push_subscriptions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("-updated_at",)},
        ),
        migrations.CreateModel(
            name="WebPushDelivery",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=__import__("uuid").uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                (
                    "sent_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                ("last_error", models.TextField(blank=True)),
                (
                    "notification",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="web_push_deliveries",
                        to="notifications.notification",
                    ),
                ),
                (
                    "subscription",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="deliveries",
                        to="notifications.webpushsubscription",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="webpushsubscription",
            index=models.Index(
                fields=["user", "disabled_at", "-updated_at"],
                name="notif_push_user_active_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="webpushdelivery",
            constraint=models.UniqueConstraint(
                fields=("notification", "subscription"),
                name="notif_push_delivery_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="webpushdelivery",
            index=models.Index(
                fields=["sent_at", "created_at"],
                name="notif_push_pending_idx",
            ),
        ),
    ]
