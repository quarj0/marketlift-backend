from django.conf import settings
from django.db import models

from marketlift.common.models import UUIDTimeStampedModel


class SellerPaymentAccount(UUIDTimeStampedModel):
    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        RESTRICTED = "restricted", "Restricted"
        REJECTED = "rejected", "Rejected"

    class PayoutMethod(models.TextChoices):
        PIX = "pix", "Pix"
        BANK_ACCOUNT = "bank_account", "Bank account"

    seller = models.OneToOneField(
        "sellers.SellerProfile", on_delete=models.CASCADE, related_name="payment_account"
    )
    provider = models.CharField(max_length=32, default="pagarme")
    provider_recipient_id = models.CharField(
        max_length=120, null=True, blank=True, unique=True, db_index=True
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.NOT_STARTED, db_index=True
    )
    payout_method = models.CharField(
        max_length=20, choices=PayoutMethod.choices, blank=True
    )
    payout_destination_masked = models.CharField(max_length=160, blank=True)
    payouts_enabled = models.BooleanField(default=False)
    kyc_url = models.URLField(max_length=1000, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-updated_at",)


class Order(UUIDTimeStampedModel):
    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Pending payment"
        PAID = "paid", "Paid"
        AWAITING_SELLER = "awaiting_seller", "Awaiting seller"
        PROCESSING = "processing", "Processing"
        SHIPPED = "shipped", "Shipped"
        OUT_FOR_DELIVERY = "out_for_delivery", "Out for delivery"
        DELIVERED = "delivered", "Delivered"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        REFUND_PENDING = "refund_pending", "Refund pending"
        REFUNDED = "refunded", "Refunded"
        DISPUTED = "disputed", "Disputed"

    class FulfillmentMethod(models.TextChoices):
        SHIPPING = "shipping", "Shipping"
        LOCAL_DELIVERY = "local_delivery", "Local delivery"
        PICKUP = "pickup", "Pickup"

    reference = models.CharField(max_length=40, unique=True, db_index=True)
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="commerce_orders"
    )
    seller = models.ForeignKey(
        "sellers.SellerProfile", on_delete=models.PROTECT, related_name="commerce_orders"
    )
    listing = models.ForeignKey(
        "listings.Listing", on_delete=models.PROTECT, related_name="commerce_orders"
    )
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.PENDING_PAYMENT, db_index=True
    )
    fulfillment_method = models.CharField(
        max_length=20, choices=FulfillmentMethod.choices
    )
    quantity = models.PositiveIntegerField(default=1)
    unit_price_cents = models.PositiveBigIntegerField()
    subtotal_cents = models.PositiveBigIntegerField()
    shipping_amount_cents = models.PositiveBigIntegerField(default=0)
    total_cents = models.PositiveBigIntegerField()
    marketplace_fee_cents = models.PositiveBigIntegerField(default=0)
    seller_proceeds_cents = models.PositiveBigIntegerField(default=0)
    currency = models.CharField(max_length=3, default="BRL")
    shipping_address = models.JSONField(default=dict, blank=True)
    listing_snapshot = models.JSONField(default=dict)
    paid_at = models.DateTimeField(null=True, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("buyer", "-created_at")),
            models.Index(fields=("seller", "status", "-created_at")),
            models.Index(fields=("listing", "status")),
        ]


class CommercePayment(UUIDTimeStampedModel):
    class Method(models.TextChoices):
        PIX = "pix", "Pix"
        CARD = "card", "Card"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"
        PARTIALLY_REFUNDED = "partially_refunded", "Partially refunded"
        CHARGEBACK = "chargeback", "Chargeback"

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments")
    provider = models.CharField(max_length=32, default="pagarme")
    method = models.CharField(max_length=12, choices=Method.choices)
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    idempotency_key = models.CharField(max_length=100, unique=True)
    provider_order_id = models.CharField(max_length=120, blank=True, db_index=True)
    provider_charge_id = models.CharField(max_length=120, blank=True, db_index=True)
    provider_transaction_id = models.CharField(max_length=120, blank=True, db_index=True)
    amount_cents = models.PositiveBigIntegerField()
    checkout_data = models.JSONField(default=dict, blank=True)
    provider_status = models.CharField(max_length=80, blank=True)
    failure_message = models.TextField(blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)


class Settlement(UUIDTimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        HELD = "held", "Held"
        AVAILABLE = "available", "Available"
        PAYOUT_REQUESTED = "payout_requested", "Payout requested"
        PAID = "paid", "Paid"
        BLOCKED = "blocked", "Blocked"

    order = models.OneToOneField(Order, on_delete=models.PROTECT, related_name="settlement")
    seller = models.ForeignKey(
        "sellers.SellerProfile", on_delete=models.PROTECT, related_name="settlements"
    )
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    amount_cents = models.PositiveBigIntegerField()
    release_after = models.DateTimeField(null=True, blank=True, db_index=True)
    provider_transfer_id = models.CharField(max_length=120, blank=True, db_index=True)
    payout_requested_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("seller", "status", "release_after"))]


class LedgerEntry(UUIDTimeStampedModel):
    class Kind(models.TextChoices):
        ORDER_PAYMENT = "order_payment", "Order payment"
        MARKETPLACE_FEE = "marketplace_fee", "Marketplace fee"
        SELLER_RECEIVABLE = "seller_receivable", "Seller receivable"
        REFUND = "refund", "Refund"
        SELLER_PAYOUT = "seller_payout", "Seller payout"

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="ledger_entries")
    seller = models.ForeignKey(
        "sellers.SellerProfile", on_delete=models.PROTECT, related_name="ledger_entries"
    )
    kind = models.CharField(max_length=24, choices=Kind.choices)
    amount_cents = models.BigIntegerField()
    currency = models.CharField(max_length=3, default="BRL")
    provider_reference = models.CharField(max_length=160, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("created_at",)
        indexes = [models.Index(fields=("seller", "kind", "created_at"))]


class Shipment(UUIDTimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        READY = "ready", "Ready"
        SHIPPED = "shipped", "Shipped"
        OUT_FOR_DELIVERY = "out_for_delivery", "Out for delivery"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"

    order = models.OneToOneField(Order, on_delete=models.PROTECT, related_name="shipment")
    provider = models.CharField(max_length=40, blank=True)
    carrier = models.CharField(max_length=80, blank=True)
    tracking_code = models.CharField(max_length=160, blank=True, db_index=True)
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    delivery_pin_hash = models.CharField(max_length=128, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    proof = models.JSONField(default=dict, blank=True)


class Dispute(UUIDTimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED_BUYER = "resolved_buyer", "Resolved for buyer"
        RESOLVED_SELLER = "resolved_seller", "Resolved for seller"
        CLOSED = "closed", "Closed"

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="disputes")
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="commerce_disputes"
    )
    reason = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    evidence = models.JSONField(default=list, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)


class ProviderWebhookEvent(UUIDTimeStampedModel):
    provider = models.CharField(max_length=32, default="pagarme")
    provider_event_id = models.CharField(max_length=160)
    event_type = models.CharField(max_length=100, blank=True)
    payload_hash = models.CharField(max_length=64)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("provider", "provider_event_id"),
                name="commerce_unique_provider_event",
            )
        ]
