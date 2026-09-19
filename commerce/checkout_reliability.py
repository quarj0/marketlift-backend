from __future__ import annotations

import secrets
import uuid

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from listings.models import Listing

from .models import CommercePayment, Order, SellerPaymentAccount, Settlement, Shipment
from .policy_models import ListingCommerceSettings
from .providers.base import CommerceProviderError
from .services import (
    _snapshot_listing,
    _validate_checkout_replay,
    listing_commerce_state,
    money_to_cents,
)

FAILED_PROVIDER_STATUSES = {
    "failed",
    "refused",
    "declined",
    "not_authorized",
    "not_authorised",
}
CANCELLED_PROVIDER_STATUSES = {"canceled", "cancelled"}


def _restore_reserved_stock(*, order: Order) -> None:
    """Return a checkout reservation exactly once while the order is still pending."""
    if order.status != Order.Status.PENDING_PAYMENT:
        return
    try:
        config = ListingCommerceSettings.objects.select_for_update().get(
            listing_id=order.listing_id
        )
    except ListingCommerceSettings.DoesNotExist:
        return
    config.stock_quantity += order.quantity
    config.save(update_fields=("stock_quantity", "updated_at"))


def _finalize_definitive_provider_error(
    *, payment_id, exc: CommerceProviderError
) -> tuple[Order, CommercePayment]:
    """Cancel a locally reserved checkout after a definitive provider rejection."""
    with transaction.atomic():
        payment = (
            CommercePayment.objects.select_for_update()
            .select_related("order")
            .get(pk=payment_id)
        )
        order = Order.objects.select_for_update().get(pk=payment.order_id)
        if payment.status != CommercePayment.Status.PENDING:
            return order, payment

        payment.status = CommercePayment.Status.FAILED
        payment.provider_status = (
            f"request_failed_{exc.status_code}" if exc.status_code else "request_failed"
        )
        payment.failure_message = str(exc)[:1000]
        payment.save(
            update_fields=(
                "status",
                "provider_status",
                "failure_message",
                "updated_at",
            )
        )
        if order.status == Order.Status.PENDING_PAYMENT:
            _restore_reserved_stock(order=order)
            order.status = Order.Status.CANCELLED
            order.cancelled_at = timezone.now()
            order.save(update_fields=("status", "cancelled_at", "updated_at"))
        return order, payment


def _create_or_get_local_checkout(
    *,
    buyer,
    listing_id,
    quantity: int,
    fulfillment_method: str,
    normalized_address: dict,
    payment_method: str,
    scoped_key: str,
) -> tuple[Order, CommercePayment]:
    """Persist the order and stock reservation before any Stripe API call."""
    with transaction.atomic():
        buyer.__class__.objects.select_for_update().only("pk").get(pk=buyer.pk)
        previous = (
            CommercePayment.objects.select_for_update()
            .select_related("order")
            .filter(idempotency_key=scoped_key)
            .first()
        )
        if previous:
            _validate_checkout_replay(
                previous=previous,
                buyer=buyer,
                listing_id=listing_id,
                quantity=quantity,
                fulfillment_method=fulfillment_method,
                payment_method=payment_method,
                shipping_address=normalized_address,
            )
            return previous.order, previous

        try:
            listing = (
                Listing.objects.select_for_update()
                .select_related("seller", "seller__user")
                .prefetch_related("media", "attribute_values")
                .get(pk=str(listing_id))
            )
        except (Listing.DoesNotExist, ValueError) as exc:
            raise ValidationError({"listingId": "Listing was not found."}) from exc

        if listing.seller.user_id == buyer.id:
            raise ValidationError("You cannot buy your own listing.")
        state = listing_commerce_state(listing)
        if not state["checkout_enabled"]:
            raise ValidationError(
                {"checkout": "Online checkout is unavailable for this listing."}
            )
        if fulfillment_method not in state["fulfillment_methods"]:
            raise ValidationError(
                {"fulfillmentMethod": "This delivery method is unavailable."}
            )

        config = ListingCommerceSettings.objects.select_for_update().get(
            listing=listing
        )
        if config.stock_quantity < quantity:
            raise ValidationError({"quantity": "Not enough stock is available."})
        account = SellerPaymentAccount.objects.select_for_update().get(
            seller=listing.seller
        )
        if account.provider != "stripe" or not account.provider_recipient_id:
            raise ValidationError("Seller Stripe account is not configured.")

        unit_price_cents = money_to_cents(listing.price)
        subtotal_cents = unit_price_cents * quantity
        max_checkout_value_cents = state["max_checkout_value_cents"]
        if (
            max_checkout_value_cents is not None
            and subtotal_cents > max_checkout_value_cents
        ):
            raise ValidationError(
                {"quantity": "This quantity exceeds the category checkout-value limit."}
            )

        fee_bps = int(getattr(settings, "MARKETLIFT_COMMERCE_FEE_BPS", 500))
        marketplace_fee_cents = subtotal_cents * fee_bps // 10000
        shipping_amount_cents = (
            int(getattr(settings, "MARKETLIFT_LOCAL_DELIVERY_FEE_CENTS", 0))
            if fulfillment_method == Order.FulfillmentMethod.LOCAL_DELIVERY
            else 0
        )
        total_cents = subtotal_cents + shipping_amount_cents
        seller_proceeds_cents = subtotal_cents - marketplace_fee_cents

        reference = f"ML-{uuid.uuid4().hex[:12].upper()}"
        order = Order.objects.create(
            reference=reference,
            buyer=buyer,
            seller=listing.seller,
            listing=listing,
            fulfillment_method=fulfillment_method,
            quantity=quantity,
            unit_price_cents=unit_price_cents,
            subtotal_cents=subtotal_cents,
            shipping_amount_cents=shipping_amount_cents,
            total_cents=total_cents,
            marketplace_fee_cents=marketplace_fee_cents,
            seller_proceeds_cents=seller_proceeds_cents,
            currency="BRL",
            shipping_address=normalized_address,
            listing_snapshot=_snapshot_listing(listing),
        )
        shipment = Shipment.objects.create(order=order)
        if fulfillment_method == Order.FulfillmentMethod.LOCAL_DELIVERY:
            pin = f"{secrets.randbelow(900000) + 100000:06d}"
            shipment.delivery_pin_hash = make_password(pin)
            shipment.proof = {"delivery_pin_issued": True}
            shipment.save(update_fields=("delivery_pin_hash", "proof", "updated_at"))
            order.listing_snapshot["delivery_pin"] = pin
            order.save(update_fields=("listing_snapshot", "updated_at"))

        Settlement.objects.create(
            order=order,
            seller=listing.seller,
            amount_cents=seller_proceeds_cents,
        )
        payment = CommercePayment.objects.create(
            order=order,
            provider="stripe",
            method=payment_method,
            amount_cents=total_cents,
            idempotency_key=scoped_key,
        )

        config.stock_quantity -= quantity
        config.save(update_fields=("stock_quantity", "updated_at"))
        return order, payment


def create_checkout_order(**kwargs):
    """Compatibility entry point; Stripe owns checkout orchestration."""
    from .stripe_runtime import create_checkout_order as stripe_create_checkout_order

    return stripe_create_checkout_order(**kwargs)
