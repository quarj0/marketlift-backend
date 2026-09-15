import base64
import hashlib
import uuid

import django.db.models.deletion
from cryptography.fernet import Fernet
from django.conf import settings
from django.db import migrations, models


def _fernet():
    secret = str(settings.SECRET_KEY).encode("utf-8")
    digest = hashlib.sha256(b"marketlift:delivery-pin:v1:" + secret).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def secure_existing_delivery_pins(apps, schema_editor):
    Shipment = apps.get_model("payments", "Shipment")
    DeliveryAssignment = apps.get_model("payments", "DeliveryAssignment")
    cipher = _fernet()

    for shipment in Shipment.objects.select_related("order").filter(
        order__fulfillment_method="local_delivery"
    ).iterator():
        snapshot = dict(shipment.order.listing_snapshot or {})
        raw_pin = str(snapshot.pop("delivery_pin", "") or "").strip()
        defaults = {}
        if raw_pin and len(raw_pin) == 6 and raw_pin.isdigit() and not shipment.delivered_at:
            defaults["delivery_pin_ciphertext"] = cipher.encrypt(
                raw_pin.encode("ascii")
            ).decode("ascii")
        DeliveryAssignment.objects.get_or_create(shipment_id=shipment.id, defaults=defaults)
        if shipment.order.listing_snapshot != snapshot:
            shipment.order.listing_snapshot = snapshot
            shipment.order.save(update_fields=("listing_snapshot", "updated_at"))


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0004_settlement_payout_idempotency_key"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DeliveryRider",
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
                ("active", models.BooleanField(db_index=True, default=True)),
                (
                    "activated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="delivery_rider",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("user__full_name", "user__email")},
        ),
        migrations.CreateModel(
            name="DeliveryAssignment",
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
                ("assigned_at", models.DateTimeField(blank=True, null=True)),
                ("delivery_pin_ciphertext", models.TextField(blank=True)),
                ("delivery_pin_failure_count", models.PositiveSmallIntegerField(default=0)),
                ("delivery_pin_locked_until", models.DateTimeField(blank=True, null=True)),
                (
                    "confirmation_source",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("rider_pin", "Rider PIN"),
                            ("buyer_confirmation", "Buyer confirmation"),
                            ("admin_override", "Administrator override"),
                            ("admin_pin", "Administrator PIN"),
                        ],
                        max_length=32,
                    ),
                ),
                ("admin_override_reason", models.TextField(blank=True)),
                (
                    "assigned_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "delivered_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "rider",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assignments",
                        to="payments.deliveryrider",
                    ),
                ),
                (
                    "shipment",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="delivery_assignment",
                        to="payments.shipment",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [
                    models.Index(
                        fields=["rider", "assigned_at"],
                        name="delivery_assignment_rider_idx",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="DeliveryConfirmationAttempt",
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
                ("source", models.CharField(max_length=32)),
                ("success", models.BooleanField(db_index=True, default=False)),
                ("reason", models.CharField(blank=True, max_length=120)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "assignment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="confirmation_attempts",
                        to="payments.deliveryassignment",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [
                    models.Index(
                        fields=["assignment", "-created_at"],
                        name="delivery_attempt_assign_idx",
                    )
                ],
            },
        ),
        migrations.RunPython(
            secure_existing_delivery_pins,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
