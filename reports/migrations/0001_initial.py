from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion, uuid


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("listings", "0001_initial"),
        ("sellers", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="Report",
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
                    "reference",
                    models.CharField(editable=False, max_length=20, unique=True),
                ),
                (
                    "target_type",
                    models.CharField(
                        choices=[
                            ("listing", "Listing"),
                            ("seller", "Seller"),
                            ("user", "User"),
                        ],
                        max_length=16,
                    ),
                ),
                ("target_label_snapshot", models.CharField(max_length=240)),
                (
                    "reason",
                    models.CharField(
                        choices=[
                            ("account", "Account"),
                            ("payment", "Payment"),
                            ("moderation", "Moderation"),
                            ("safety", "Safety"),
                            ("technical", "Technical"),
                            ("other", "Other"),
                        ],
                        max_length=16,
                    ),
                ),
                ("statement", models.TextField()),
                (
                    "priority",
                    models.CharField(
                        choices=[
                            ("low", "Low"),
                            ("medium", "Medium"),
                            ("high", "High"),
                        ],
                        db_index=True,
                        default="medium",
                        max_length=10,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("open", "Open"),
                            ("review", "Review"),
                            ("resolved", "Resolved"),
                            ("dismissed", "Dismissed"),
                        ],
                        db_index=True,
                        default="open",
                        max_length=16,
                    ),
                ),
                ("internal_note", models.TextField(blank=True)),
                ("decision_reason", models.TextField(blank=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                (
                    "assigned_to",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assigned_reports",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "decided_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="decided_reports",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "listing",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reports",
                        to="listings.listing",
                    ),
                ),
                (
                    "reporter",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="submitted_reports",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "seller",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reports",
                        to="sellers.sellerprofile",
                    ),
                ),
                (
                    "user_target",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reports_received",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [
                    models.Index(
                        fields=["status", "priority", "-created_at"],
                        name="reports_rep_status_303c42_idx",
                    ),
                    models.Index(
                        fields=["target_type", "-created_at"],
                        name="reports_rep_target__e9a682_idx",
                    ),
                ],
            },
        )
    ]
