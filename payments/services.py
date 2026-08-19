from __future__ import annotations

import uuid
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from notifications.services import create_notification
from promotions.models import ListingPromotion
from subscriptions.services import activate_paid_subscription
from .models import Payment
from .providers import get_payment_provider
from .providers.base import PaymentProviderError, ProviderResult


def _reference():
    return f"ML_{uuid.uuid4().hex.upper()}"[:64]


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _status_from_provider(status: str, detail: str = ""):
    status = (status or "").lower()
    detail = (detail or "").lower()
    if status == "processed" or detail == "accredited":
        return Payment.Status.PAID
    if status == "refunded" or detail == "refunded":
        return Payment.Status.REFUNDED
    if status in {"cancelled", "canceled", "expired"}:
        return Payment.Status.CANCELLED
    if status in {"failed", "rejected"}:
        return Payment.Status.FAILED
    return Payment.Status.PENDING


def _split_name(full_name: str):
    bits = (full_name or "").strip().split(maxsplit=1)
    return (bits[0] if bits else "Marketlift", bits[1] if len(bits) > 1 else "User")


def build_payer(*, user, payer: dict | None, method: str):
    payer = dict(payer or {})
    first, last = _split_name(user.full_name)
    result = {
        "email": payer.get("email") or user.email,
        "first_name": payer.get("first_name") or first,
        "last_name": payer.get("last_name") or last,
    }
    identification_type = (payer.get("identification_type") or "").strip()
    identification_number = (payer.get("identification_number") or "").strip()
    if identification_type or identification_number:
        if not identification_type or not identification_number:
            raise ValidationError(
                "Both identification type and number are required together."
            )
        result["identification"] = {
            "type": identification_type,
            "number": identification_number,
        }
    if method == Payment.Method.BOLETO:
        required = (
            "identification_type",
            "identification_number",
            "zip_code",
            "street_name",
            "street_number",
            "neighborhood",
            "city",
            "state",
        )
        missing = [k for k in required if not str(payer.get(k) or "").strip()]
        if missing:
            raise ValidationError({"payer": f"Boleto requires: {', '.join(missing)}."})
        result["identification"] = {
            "type": identification_type,
            "number": identification_number,
        }
        result["address"] = {
            "zip_code": payer["zip_code"],
            "street_name": payer["street_name"],
            "street_number": payer["street_number"],
            "neighborhood": payer["neighborhood"],
            "city": payer["city"],
            "state": str(payer["state"]).upper(),
        }
    return result


@transaction.atomic
def create_subscription_payment(
    *,
    seller,
    plan,
    billing_cycle: str,
    method: str,
    idempotency_key: str,
    payer=None,
    card=None,
    request=None,
):
    from subscriptions.models import SellerSubscription

    if seller.is_suspended:
        raise ValidationError("Selling access is suspended.")
    if not plan.active:
        raise ValidationError("This seller plan is unavailable.")
    if billing_cycle not in SellerSubscription.BillingCycle.values:
        raise ValidationError({"billingCycle": "Invalid billing cycle."})
    if method not in Payment.Method.values:
        raise ValidationError({"method": "Invalid payment method."})
    if plan.code == "free":
        raise ValidationError("The Free plan does not require a payment.")
    key = (idempotency_key or "").strip()
    if not key:
        raise ValidationError({"idempotencyKey": "An idempotency key is required."})
    existing = Payment.objects.filter(idempotency_key=key).first()
    if existing:
        if existing.seller_id != seller.id:
            raise ValidationError("This idempotency key belongs to another payment.")
        return existing
    amount = _money(
        plan.yearly_price
        if billing_cycle == SellerSubscription.BillingCycle.YEARLY
        else plan.monthly_price
    )
    payment = Payment(
        user=seller.user,
        seller=seller,
        purpose=Payment.Purpose.SUBSCRIPTION,
        method=method,
        amount=amount,
        reference=_reference(),
        idempotency_key=key,
        provider=get_payment_provider().name,
        seller_plan=plan,
        billing_cycle=billing_cycle,
    )
    payment.full_clean()
    payment.save()
    _send_to_provider(
        payment=payment,
        payer=build_payer(user=seller.user, payer=payer, method=method),
        card=card,
        request=request,
    )
    return payment


@transaction.atomic
def create_promotion_payment(
    *,
    seller,
    listing,
    product,
    method: str,
    idempotency_key: str,
    payer=None,
    card=None,
    request=None,
):
    if seller.is_suspended:
        raise ValidationError("Selling access is suspended.")
    if listing.seller_id != seller.id:
        raise ValidationError("You can only promote your own listing.")
    if listing.status != listing.Status.PUBLISHED:
        raise ValidationError("Only published listings can be promoted.")
    if not product.active:
        raise ValidationError("This promotion is unavailable.")
    if method not in Payment.Method.values:
        raise ValidationError({"method": "Invalid payment method."})
    key = (idempotency_key or "").strip()
    if not key:
        raise ValidationError({"idempotencyKey": "An idempotency key is required."})
    existing = Payment.objects.filter(idempotency_key=key).first()
    if existing:
        if existing.seller_id != seller.id:
            raise ValidationError("This idempotency key belongs to another payment.")
        return existing
    payment = Payment(
        user=seller.user,
        seller=seller,
        purpose=Payment.Purpose.PROMOTION,
        method=method,
        amount=_money(product.price),
        reference=_reference(),
        idempotency_key=key,
        provider=get_payment_provider().name,
        listing=listing,
        promotion_product=product,
    )
    payment.full_clean()
    payment.save()
    _send_to_provider(
        payment=payment,
        payer=build_payer(user=seller.user, payer=payer, method=method),
        card=card,
        request=request,
    )
    return payment


def _send_to_provider(*, payment, payer, card, request=None):
    provider = get_payment_provider()
    try:
        result = provider.create_order(payment=payment, payer=payer, card=card)
    except PaymentProviderError as exc:
        payment.status = Payment.Status.FAILED
        payment.failure_message = str(exc)
        payment.failed_at = timezone.now()
        payment.save(
            update_fields=("status", "failure_message", "failed_at", "updated_at")
        )
        raise ValidationError(str(exc)) from exc
    sync_payment_from_provider(payment=payment, result=result, request=request)


@transaction.atomic
def sync_payment_from_provider(
    *, payment: Payment, result: ProviderResult, request=None
):
    old = payment.status
    payment.provider_order_id = result.order_id or payment.provider_order_id
    payment.provider_payment_id = result.payment_id or payment.provider_payment_id
    payment.provider_status = result.status
    payment.provider_status_detail = result.status_detail
    payment.checkout_data = result.checkout_data or payment.checkout_data or {}
    new = _status_from_provider(result.status, result.status_detail)
    if (
        payment.status in {Payment.Status.PAID, Payment.Status.REFUNDED}
        and new == Payment.Status.PENDING
    ):
        new = payment.status
    payment.status = new
    now = timezone.now()
    if new == Payment.Status.PAID and not payment.paid_at:
        payment.paid_at = now
    if new == Payment.Status.FAILED and not payment.failed_at:
        payment.failed_at = now
    if new == Payment.Status.CANCELLED and not payment.cancelled_at:
        payment.cancelled_at = now
    if new == Payment.Status.REFUNDED and not payment.refunded_at:
        payment.refunded_at = now
    payment.save()
    if new == Payment.Status.PAID:
        _fulfil_paid_payment(payment=payment, request=request)
    if old != new:
        record_audit_event(
            actor=None,
            action=f"payment.{new}",
            target=payment,
            target_type="payment",
            target_label=payment.reference,
            metadata={
                "provider": payment.provider,
                "provider_status": result.status,
                "purpose": payment.purpose,
            },
            request=request,
        )
        create_notification(
            user=payment.user,
            notification_type="payment",
            title=(
                "Payment confirmed"
                if new == Payment.Status.PAID
                else f"Payment {payment.get_status_display().lower()}"
            ),
            body=f"Marketlift payment {payment.reference} is {payment.get_status_display().lower()}.",
            href="/selling/payments",
            data={"payment_id": str(payment.id), "status": new},
        )
    return payment


@transaction.atomic
def _fulfil_paid_payment(*, payment: Payment, request=None):
    if payment.purpose == Payment.Purpose.SUBSCRIPTION:
        if payment.subscription_id:
            return payment
        subscription = activate_paid_subscription(
            seller=payment.seller,
            plan=payment.seller_plan,
            billing_cycle=payment.billing_cycle,
            actor=payment.user,
            request=request,
        )
        payment.subscription = subscription
        payment.save(update_fields=("subscription", "updated_at"))
        return payment
    if payment.purpose == Payment.Purpose.PROMOTION:
        if payment.listing_promotion_id:
            return payment
        from datetime import timedelta

        activation = ListingPromotion.objects.create(
            listing=payment.listing,
            product=payment.promotion_product,
            source=ListingPromotion.Source.PURCHASE,
            starts_at=timezone.now(),
            ends_at=timezone.now()
            + timedelta(days=payment.promotion_product.duration_days),
        )
        payment.listing_promotion = activation
        payment.save(update_fields=("listing_promotion", "updated_at"))
        create_notification(
            user=payment.user,
            notification_type="promotion",
            title="Promotion activated",
            body=f"{payment.promotion_product.name} is now active for {payment.listing.title}.",
            href="/selling/listings",
        )
        return payment


def refresh_payment(*, payment, request=None):
    if not payment.provider_order_id:
        return payment
    provider = get_payment_provider()
    if provider.name != payment.provider:
        return payment
    try:
        result = provider.get_order(payment.provider_order_id)
    except PaymentProviderError as exc:
        raise ValidationError(str(exc)) from exc
    return sync_payment_from_provider(payment=payment, result=result, request=request)
