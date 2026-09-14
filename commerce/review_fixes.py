from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .models import CommercePayment, LedgerEntry, Order, Settlement
from .policy_models import ListingCommerceSettings
from .services import (
    activate_seller_payments as _activate_seller_payments,
    finalize_order_refund as _finalize_order_refund,
    open_order_dispute as _open_order_dispute,
    refund_order as _refund_order,
    release_due_settlements,
    withdraw_available_balance as _withdraw_available_balance,
)


PAID_FULFILLMENT_STATES = {
    Order.Status.AWAITING_SELLER,
    Order.Status.PROCESSING,
    Order.Status.SHIPPED,
    Order.Status.OUT_FOR_DELIVERY,
    Order.Status.DELIVERED,
}

RESTOCKABLE_REFUND_STATES = {
    Order.Status.PAID,
    Order.Status.AWAITING_SELLER,
    Order.Status.PROCESSING,
}

SUCCESSFUL_TRANSFER_STATUSES = {"paid", "transferred", "completed", "success", "succeeded"}


def activate_seller_payments(*, seller, recipient_payload: dict, payout_method: str):
    if getattr(seller, "seller_type", "individual") != "individual":
        raise ValidationError(
            "Business seller payout onboarding is not available until the CNPJ recipient flow is enabled."
        )
    return _activate_seller_payments(
        seller=seller,
        recipient_payload=recipient_payload,
        payout_method=payout_method,
    )


def open_order_dispute(*, order: Order, user, reason: str, description: str):
    current = Order.objects.select_related("seller", "seller__user").get(pk=order.pk)
    if current.paid_at is None or current.status not in PAID_FULFILLMENT_STATES:
        raise ValidationError("Only a paid order in fulfillment can be disputed.")
    return _open_order_dispute(
        order=current,
        user=user,
        reason=reason,
        description=description,
    )


def seller_wallet(seller) -> dict:
    release_due_settlements(seller=seller)
    eligible = Settlement.objects.filter(seller=seller).exclude(
        order__status__in=(Order.Status.CANCELLED, Order.Status.REFUNDED)
    )
    pending_cents = int(
        eligible.filter(
            Q(status__in=(Settlement.Status.PENDING, Settlement.Status.HELD))
            | Q(status=Settlement.Status.BLOCKED, order__status=Order.Status.DISPUTED)
        ).aggregate(total=Sum("amount_cents"))["total"]
        or 0
    )
    available_cents = int(
        eligible.filter(status=Settlement.Status.AVAILABLE).aggregate(total=Sum("amount_cents"))["total"]
        or 0
    )
    payout_requested_cents = int(
        eligible.filter(status=Settlement.Status.PAYOUT_REQUESTED).aggregate(total=Sum("amount_cents"))["total"]
        or 0
    )
    paid_out_cents = int(
        Settlement.objects.filter(seller=seller, status=Settlement.Status.PAID)
        .aggregate(total=Sum("amount_cents"))["total"]
        or 0
    )
    return {
        "pending_cents": pending_cents,
        "available_cents": available_cents,
        "payout_requested_cents": payout_requested_cents,
        "paid_out_cents": paid_out_cents,
        "currency": "BRL",
    }


def _restore_refunded_stock(order: Order, previous_status: str) -> None:
    if previous_status not in RESTOCKABLE_REFUND_STATES:
        return
    try:
        config = ListingCommerceSettings.objects.select_for_update().get(listing=order.listing)
    except ListingCommerceSettings.DoesNotExist:
        return
    config.stock_quantity += order.quantity
    config.save(update_fields=("stock_quantity", "updated_at"))


def finalize_order_refund(*, payment: CommercePayment, reason: str = "", provider_status: str = "refunded") -> Order:
    with transaction.atomic():
        locked_payment = CommercePayment.objects.select_for_update().select_related("order").get(pk=payment.pk)
        previous_status = locked_payment.order.status
        already_refunded = locked_payment.status == CommercePayment.Status.REFUNDED
        order = _finalize_order_refund(
            payment=locked_payment,
            reason=reason,
            provider_status=provider_status,
        )
        if not already_refunded:
            _restore_refunded_stock(order, previous_status)
        return order


def refund_order(*, order: Order, reason: str = "") -> Order:
    with transaction.atomic():
        locked_order = Order.objects.select_for_update().get(pk=order.pk)
        previous_status = locked_order.status
        result = _refund_order(order=locked_order, reason=reason)
        _restore_refunded_stock(result, previous_status)
        return result


def withdraw_available_balance(*, seller) -> dict:
    payload = _withdraw_available_balance(seller=seller)
    transfer_id = str(payload.get("transfer_id") or "").strip()
    status = str(payload.get("status") or "").strip().lower()
    if transfer_id and status in SUCCESSFUL_TRANSFER_STATUSES:
        with transaction.atomic():
            now = timezone.now()
            rows = Settlement.objects.select_for_update().filter(
                seller=seller,
                provider_transfer_id=transfer_id,
                status=Settlement.Status.PAYOUT_REQUESTED,
            )
            rows.update(status=Settlement.Status.PAID, paid_at=now, updated_at=now)
    return payload


def requeue_failed_transfer(*, transfer_id: str) -> int:
    if not transfer_id:
        return 0
    with transaction.atomic():
        rows = list(
            Settlement.objects.select_for_update().filter(
                provider_transfer_id=transfer_id,
                status=Settlement.Status.PAYOUT_REQUESTED,
            )
        )
        if not rows:
            return 0
        for settlement in rows:
            settlement.status = Settlement.Status.AVAILABLE
            settlement.provider_transfer_id = ""
            settlement.payout_idempotency_key = ""
            settlement.payout_requested_at = None
            settlement.save(
                update_fields=(
                    "status",
                    "provider_transfer_id",
                    "payout_idempotency_key",
                    "payout_requested_at",
                    "updated_at",
                )
            )
            LedgerEntry.objects.filter(
                order=settlement.order,
                seller=settlement.seller,
                kind=LedgerEntry.Kind.SELLER_PAYOUT,
                provider_reference=transfer_id,
            ).delete()
        return len(rows)
