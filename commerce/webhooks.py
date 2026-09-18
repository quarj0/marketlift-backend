from __future__ import annotations

from django.utils import timezone

from .models import CommercePayment, Dispute, Order, Settlement
from .policy_models import ListingCommerceSettings


def _restore_order_stock(payment: CommercePayment) -> None:
    order = payment.order
    if order.status != order.Status.PENDING_PAYMENT:
        return
    try:
        config = ListingCommerceSettings.objects.select_for_update().get(
            listing=order.listing
        )
    except ListingCommerceSettings.DoesNotExist:
        return
    config.stock_quantity += order.quantity
    config.save(update_fields=("stock_quantity", "updated_at"))
    order.status = order.Status.CANCELLED
    order.cancelled_at = timezone.now()
    order.save(update_fields=("status", "cancelled_at", "updated_at"))


def _record_chargeback_recovery(payment: CommercePayment, event_type: str) -> None:
    order = (
        Order.objects.select_for_update()
        .select_related("buyer")
        .get(pk=payment.order_id)
    )
    order.status = Order.Status.DISPUTED
    order.save(update_fields=("status", "updated_at"))
    settlement = Settlement.objects.select_for_update().filter(order=order).first()
    if settlement and settlement.status not in {
        Settlement.Status.PAID,
        Settlement.Status.PAYOUT_REQUESTED,
    }:
        settlement.status = Settlement.Status.BLOCKED
        settlement.release_after = None
        settlement.save(update_fields=("status", "release_after", "updated_at"))
    if not order.disputes.filter(status=Dispute.Status.OPEN).exists():
        Dispute.objects.create(
            order=order,
            opened_by=order.buyer,
            reason="provider_chargeback",
            description=(
                "Stripe reported a chargeback. Fulfillment is blocked "
                f"pending financial review ({event_type})."
            ),
            evidence=[{"source": "stripe", "event_type": event_type}],
        )
