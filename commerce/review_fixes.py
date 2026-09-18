from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .models import (
    CommercePayment,
    LedgerEntry,
    Order,
    SellerPaymentAccount,
    Settlement,
)
from .policy_models import ListingCommerceSettings
from .providers.base import CommerceProviderError
from .services import (
    _normalize_shipping_address,
    _scoped_checkout_idempotency_key,
    _validate_checkout_replay,
    finalize_order_refund as _finalize_order_refund,
    open_order_dispute as _open_order_dispute,
    refund_order as _refund_order,
    release_due_settlements,
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

SUCCESSFUL_TRANSFER_STATUSES = {
    "paid",
    "transferred",
    "completed",
    "success",
    "succeeded",
}
FAILED_TRANSFER_STATUSES = {
    "failed",
    "refused",
    "rejected",
    "canceled",
    "cancelled",
}
REJECTED_RECIPIENT_STATUSES = {
    "rejected",
    "refused",
    "denied",
    "failed",
    "canceled",
    "cancelled",
}
RESTRICTED_RECIPIENT_STATUSES = {
    "restricted",
    "blocked",
    "suspended",
    "disabled",
    "inactive",
}

def _normalize_recipient_account(account: SellerPaymentAccount) -> SellerPaymentAccount:
    provider_status = str((account.metadata or {}).get("provider_status") or "").lower()
    if provider_status in REJECTED_RECIPIENT_STATUSES:
        desired = SellerPaymentAccount.Status.REJECTED
        enabled = False
    elif provider_status in RESTRICTED_RECIPIENT_STATUSES:
        desired = SellerPaymentAccount.Status.RESTRICTED
        enabled = False
    elif provider_status in {"active", "enabled", "registered"}:
        desired = SellerPaymentAccount.Status.ACTIVE
        enabled = True
    else:
        desired = SellerPaymentAccount.Status.PENDING
        enabled = False
    if account.status != desired or account.payouts_enabled != enabled:
        account.status = desired
        account.payouts_enabled = enabled
        account.save(update_fields=("status", "payouts_enabled", "updated_at"))
    return account


def activate_seller_payments(*, seller, recipient_payload: dict, payout_method: str):
    from .stripe_runtime import activate_seller_payments as stripe_activate_seller_payments

    return stripe_activate_seller_payments(
        seller=seller,
        recipient_payload=recipient_payload,
        payout_method=payout_method,
    )

@transaction.atomic
def create_checkout_order(**kwargs):
    from .stripe_runtime import create_checkout_order as stripe_create_checkout_order

    return stripe_create_checkout_order(**kwargs)

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
        eligible.filter(status=Settlement.Status.AVAILABLE).aggregate(
            total=Sum("amount_cents")
        )["total"]
        or 0
    )
    payout_requested_cents = int(
        eligible.filter(status=Settlement.Status.PAYOUT_REQUESTED).aggregate(
            total=Sum("amount_cents")
        )["total"]
        or 0
    )
    paid_out_cents = int(
        Settlement.objects.filter(
            seller=seller, status=Settlement.Status.PAID
        ).aggregate(total=Sum("amount_cents"))["total"]
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
        config = ListingCommerceSettings.objects.select_for_update().get(
            listing=order.listing
        )
    except ListingCommerceSettings.DoesNotExist:
        return
    config.stock_quantity += order.quantity
    config.save(update_fields=("stock_quantity", "updated_at"))


def _record_refund_without_blocking_inflight_payout(
    *, payment: CommercePayment, reason: str, provider_status: str
) -> Order:
    order = Order.objects.select_for_update().get(pk=payment.order_id)
    now = timezone.now()
    payment.status = CommercePayment.Status.REFUNDED
    payment.refunded_at = payment.refunded_at or now
    payment.provider_status = provider_status or payment.provider_status
    payment.save(
        update_fields=("status", "refunded_at", "provider_status", "updated_at")
    )
    order.status = Order.Status.REFUNDED
    order.save(update_fields=("status", "updated_at"))
    if not order.ledger_entries.filter(
        kind=LedgerEntry.Kind.REFUND,
        provider_reference=payment.provider_charge_id,
    ).exists():
        LedgerEntry.objects.create(
            order=order,
            seller=order.seller,
            kind=LedgerEntry.Kind.REFUND,
            amount_cents=-order.total_cents,
            currency=order.currency,
            provider_reference=payment.provider_charge_id,
            metadata={
                "reason": reason,
                "financial_recovery_required": True,
                "payout_in_flight": True,
            },
        )
    return order


def finalize_order_refund(
    *,
    payment: CommercePayment,
    reason: str = "",
    provider_status: str = "refunded",
) -> Order:
    with transaction.atomic():
        locked_payment = (
            CommercePayment.objects.select_for_update()
            .select_related("order", "order__seller")
            .get(pk=payment.pk)
        )
        previous_status = locked_payment.order.status
        already_refunded = locked_payment.status == CommercePayment.Status.REFUNDED
        settlement = Settlement.objects.select_for_update().get(
            order_id=locked_payment.order_id
        )
        if settlement.status == Settlement.Status.PAYOUT_REQUESTED:
            return _record_refund_without_blocking_inflight_payout(
                payment=locked_payment,
                reason=reason,
                provider_status=provider_status,
            )

        order = _finalize_order_refund(
            payment=locked_payment,
            reason=reason,
            provider_status=provider_status,
        )
        if not already_refunded:
            _restore_refunded_stock(order, previous_status)
        return order


def refund_order(*, order: Order, reason: str = "") -> Order:
    # The patched finalize_order_refund called by the original service owns the
    # inventory restoration. Do not restock again here.
    return _refund_order(order=order, reason=reason)


def _requeue_unsubmitted_payout_batch(*, seller) -> int:
    """Restore a payout batch after a definitive provider-side rejection.

    Retryable/ambiguous failures deliberately keep the batch requested with its
    stable idempotency key. A definitive 4xx response proves no transfer will be
    created, so the settlements must become withdrawable again (unless a refund
    or chargeback financially blocks them).
    """
    with transaction.atomic():
        rows = list(
            Settlement.objects.select_for_update()
            .select_related("order")
            .filter(
                seller=seller,
                status=Settlement.Status.PAYOUT_REQUESTED,
                provider_transfer_id="",
            )
            .exclude(payout_idempotency_key="")
        )
        for settlement in rows:
            financially_blocked = (
                settlement.order.status == Order.Status.REFUNDED
                or settlement.order.payments.filter(
                    status=CommercePayment.Status.CHARGEBACK
                ).exists()
            )
            settlement.status = (
                Settlement.Status.BLOCKED
                if financially_blocked
                else Settlement.Status.AVAILABLE
            )
            settlement.payout_idempotency_key = ""
            settlement.payout_requested_at = None
            settlement.save(
                update_fields=(
                    "status",
                    "payout_idempotency_key",
                    "payout_requested_at",
                    "updated_at",
                )
            )
        return len(rows)


def withdraw_available_balance(*, seller) -> dict:
    from .stripe_runtime import withdraw_available_balance as stripe_withdraw_available_balance

    return stripe_withdraw_available_balance(seller=seller)

def requeue_failed_transfer(*, transfer_id: str) -> int:
    if not transfer_id:
        return 0
    with transaction.atomic():
        rows = list(
            Settlement.objects.select_for_update()
            .select_related("order")
            .filter(
                provider_transfer_id=transfer_id,
                status=Settlement.Status.PAYOUT_REQUESTED,
            )
        )
        if not rows:
            return 0
        for settlement in rows:
            # Refunds and chargebacks must never become withdrawable again if
            # an in-flight provider transfer fails.
            financially_blocked = (
                settlement.order.status == Order.Status.REFUNDED
                or settlement.order.payments.filter(
                    status=CommercePayment.Status.CHARGEBACK
                ).exists()
            )
            settlement.status = (
                Settlement.Status.BLOCKED
                if financially_blocked
                else Settlement.Status.AVAILABLE
            )
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
