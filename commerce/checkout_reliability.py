from __future__ import annotations

import secrets
import uuid

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from listings.models import Listing

from .models import CommercePayment, Order, SellerPaymentAccount, Settlement, Shipment
from .policy_models import ListingCommerceSettings
from .providers import get_commerce_provider
from .providers.base import CommerceProviderError
from .services import (
    _buyer_customer_payload,
    _checkout_data,
    _normalize_shipping_address,
    _payment_payload,
    _scoped_checkout_idempotency_key,
    _snapshot_listing,
    _validate_checkout_replay,
    approve_commerce_payment,
    listing_commerce_state,
    money_to_cents,
)

CARD_REFERENCE_SALT = "marketlift.commerce.card-reference.v1"
CARD_REFERENCE_MAX_AGE_SECONDS = 60 * 60

FAILED_PROVIDER_STATUSES = {
    "failed",
    "refused",
    "declined",
    "not_authorized",
    "not_authorised",
}
CANCELLED_PROVIDER_STATUSES = {"canceled", "cancelled"}


def _unwrap_buyer_card_reference(*, buyer, reference: str | None) -> str | None:
    if not reference:
        return None
    try:
        payload = signing.loads(
            reference,
            salt=CARD_REFERENCE_SALT,
            max_age=CARD_REFERENCE_MAX_AGE_SECONDS,
        )
    except signing.BadSignature as exc:
        raise ValidationError(
            {"cardId": "This vaulted card reference is invalid or expired."}
        ) from exc
    if not isinstance(payload, dict) or str(payload.get("buyer_id") or "") != str(
        buyer.id
    ):
        raise ValidationError(
            {"cardId": "This vaulted card does not belong to this buyer."}
        )
    card_id = str(payload.get("card_id") or "").strip()
    if not card_id:
        raise ValidationError({"cardId": "This vaulted card reference is invalid."})
    return card_id


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


def _provider_payload(
    *,
    order: Order,
    buyer,
    customer_document: str,
    customer_phone: str,
    card_id: str | None,
) -> dict:
    account = SellerPaymentAccount.objects.get(seller_id=order.seller_id)
    recipient_id = str(account.provider_recipient_id or "").strip()
    if not recipient_id:
        raise ValidationError("Seller payment recipient is not configured.")

    marketplace_recipient = str(
        getattr(settings, "PAGARME_MARKETPLACE_RECIPIENT_ID", "") or ""
    ).strip()
    if not marketplace_recipient:
        raise ValidationError("Marketplace recipient is not configured.")

    seller_amount = order.seller_proceeds_cents
    split = [
        {
            "amount": seller_amount,
            "recipient_id": recipient_id,
            "type": "flat",
            "options": {
                "charge_processing_fee": False,
                "charge_remainder_fee": False,
                "liable": False,
            },
        },
        {
            "amount": order.total_cents - seller_amount,
            "recipient_id": marketplace_recipient,
            "type": "flat",
            "options": {
                "charge_processing_fee": True,
                "charge_remainder_fee": True,
                "liable": True,
            },
        },
    ]
    title = str(order.listing_snapshot.get("title") or "Marketlift item")[:255]
    items = [
        {
            "amount": order.unit_price_cents,
            "description": title,
            "quantity": order.quantity,
            "code": str(order.listing_id),
        }
    ]
    if order.shipping_amount_cents:
        items.append(
            {
                "amount": order.shipping_amount_cents,
                "description": "Marketlift local delivery",
                "quantity": 1,
                "code": f"delivery:{order.id}",
            }
        )
    return {
        "code": order.reference,
        "items": items,
        "customer": _buyer_customer_payload(
            buyer=buyer,
            document=customer_document,
            phone=customer_phone,
        ),
        "payments": [
            _payment_payload(
                method=order.payments.order_by("-created_at").first().method,
                card_id=card_id,
                split=split,
            )
        ],
        "metadata": {
            "marketlift_order_id": str(order.id),
            "marketlift_reference": order.reference,
        },
    }


def _apply_provider_result(
    *, payment_id, result: dict
) -> tuple[Order, CommercePayment]:
    with transaction.atomic():
        payment = (
            CommercePayment.objects.select_for_update()
            .select_related("order")
            .get(pk=payment_id)
        )
        order = Order.objects.select_for_update().get(pk=payment.order_id)

        # Another concurrent replay/webhook may already have finalized this
        # payment. Never regress an approved or terminal local state.
        if payment.status != CommercePayment.Status.PENDING:
            return order, payment

        payment.provider_order_id = str(result.get("id") or "")
        charges = result.get("charges") or []
        charge = charges[0] if charges else {}
        payment.provider_charge_id = str(charge.get("id") or "")
        last_tx = charge.get("last_transaction") or {}
        payment.provider_transaction_id = str(last_tx.get("id") or "")
        payment.provider_status = str(
            charge.get("status") or result.get("status") or ""
        )
        payment.checkout_data = _checkout_data(result)

        provider_status = payment.provider_status.lower()
        if provider_status in CANCELLED_PROVIDER_STATUSES | FAILED_PROVIDER_STATUSES:
            payment.status = (
                CommercePayment.Status.CANCELLED
                if provider_status in CANCELLED_PROVIDER_STATUSES
                else CommercePayment.Status.FAILED
            )
            payment.failure_message = str(last_tx.get("acquirer_message") or "")
            payment.save()
            if order.status == Order.Status.PENDING_PAYMENT:
                _restore_reserved_stock(order=order)
                order.status = Order.Status.CANCELLED
                order.cancelled_at = timezone.now()
                order.save(update_fields=("status", "cancelled_at", "updated_at"))
            return order, payment

        payment.save()
        if provider_status in {"paid", "approved"}:
            approve_commerce_payment(payment)
            payment.refresh_from_db()
            order.refresh_from_db()
        return order, payment


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
    """Persist the order and stock reservation before any remote payment call.

    Locking the buyer row serializes reuse of the same buyer-scoped idempotency
    key even when malicious/concurrent requests point at different listings.
    """
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
            # Only lock the Listing row. Category is nullable, so joining it in a
            # SELECT ... FOR UPDATE makes PostgreSQL reject the query because the
            # nullable side of an outer join cannot be locked.
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
        if not account.provider_recipient_id:
            raise ValidationError("Seller payment recipient is not configured.")

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
            method=payment_method,
            amount_cents=total_cents,
            idempotency_key=scoped_key,
        )

        # Stock is a reservation as soon as the durable local checkout exists.
        # Definitive provider failure/cancellation returns it exactly once.
        config.stock_quantity -= quantity
        config.save(update_fields=("stock_quantity", "updated_at"))
        return order, payment


def create_checkout_order(
    *,
    buyer,
    listing_id,
    quantity: int,
    fulfillment_method: str,
    shipping_address: dict | None,
    payment_method: str,
    customer_document: str,
    customer_phone: str,
    card_id: str | None,
    idempotency_key: str,
) -> tuple[Order, CommercePayment]:
    if quantity < 1:
        raise ValidationError({"quantity": "Quantity must be at least one."})

    normalized_address = _normalize_shipping_address(
        fulfillment_method, shipping_address
    )
    scoped_key = _scoped_checkout_idempotency_key(
        buyer_id=buyer.id, raw_key=idempotency_key
    )
    provider_card_id = card_id
    if payment_method == CommercePayment.Method.CARD:
        provider_card_id = _unwrap_buyer_card_reference(buyer=buyer, reference=card_id)

    # Validate buyer/card data and provider configuration before reserving stock.
    _buyer_customer_payload(
        buyer=buyer, document=customer_document, phone=customer_phone
    )
    _payment_payload(method=payment_method, card_id=provider_card_id, split=[])
    marketplace_recipient = str(
        getattr(settings, "PAGARME_MARKETPLACE_RECIPIENT_ID", "") or ""
    ).strip()
    if not marketplace_recipient:
        raise ValidationError("Marketplace recipient is not configured.")
    provider = get_commerce_provider()

    order, payment = _create_or_get_local_checkout(
        buyer=buyer,
        listing_id=listing_id,
        quantity=quantity,
        fulfillment_method=fulfillment_method,
        normalized_address=normalized_address,
        payment_method=payment_method,
        scoped_key=scoped_key,
    )

    # A replay that already has a provider identity (or a terminal local state)
    # is complete from the request's perspective. Webhooks own later transitions.
    if (
        payment.status != CommercePayment.Status.PENDING
        or order.status != Order.Status.PENDING_PAYMENT
        or payment.provider_order_id
        or payment.provider_charge_id
    ):
        return order, payment

    provider_payload = _provider_payload(
        order=order,
        buyer=buyer,
        customer_document=customer_document,
        customer_phone=customer_phone,
        card_id=provider_card_id,
    )
    try:
        result = provider.create_order(
            payload=provider_payload, idempotency_key=scoped_key
        )
    except CommerceProviderError as exc:
        if exc.retryable:
            # Keep the durable local order/payment and stock reservation. The
            # browser can retry the same checkout key safely; if the first request
            # reached Pagar.me, its idempotency key returns the same payment.
            raise
        return _finalize_definitive_provider_error(payment_id=payment.id, exc=exc)

    return _apply_provider_result(payment_id=payment.id, result=result)
