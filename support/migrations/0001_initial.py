from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion, uuid


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("uploads", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="SupportTicket",
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
                ("subject", models.CharField(max_length=180)),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("account", "Account"),
                            ("payment", "Payment"),
                            ("listing", "Listing"),
                            ("verification", "Verification"),
                            ("safety", "Safety"),
                            ("technical", "Technical"),
                            ("other", "Other"),
                        ],
                        default="other",
                        max_length=20,
                    ),
                ),
                (
                    "priority",
                    models.CharField(
                        choices=[
                            ("low", "Low"),
                            ("medium", "Medium"),
                            ("high", "High"),
                            ("urgent", "Urgent"),
                        ],
                        db_index=True,
                        default="medium",
                        max_length=12,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("open", "Open"),
                            ("review", "In review"),
                            ("resolved", "Resolved"),
                            ("closed", "Closed"),
                        ],
                        db_index=True,
                        default="open",
                        max_length=12,
                    ),
                ),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "last_customer_message_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("last_staff_message_at", models.DateTimeField(blank=True, null=True)),
                (
                    "assigned_to",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assigned_support_tickets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="support_tickets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("-updated_at",)},
        ),
        migrations.CreateModel(
            name="SupportMessage",
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
                ("body", models.TextField(max_length=5000)),
                ("internal", models.BooleanField(default=False)),
                (
                    "sender",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="support_messages",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "ticket",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="messages",
                        to="support.supportticket",
                    ),
                ),
                (
                    "upload",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="support_messages",
                        to="uploads.uploadasset",
                    ),
                ),
            ],
            options={"ordering": ("created_at",)},
        ),
        migrations.AddIndex(
            model_name="supportticket",
            index=models.Index(
                fields=["status", "priority", "-updated_at"],
                name="support_status_prio_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="supportticket",
            index=models.Index(
                fields=["user", "-updated_at"], name="support_user_updated_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="supportmessage",
            index=models.Index(
                fields=["ticket", "created_at"], name="support_msg_ticket_idx"
            ),
        ),
    ]
