from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import CommercePayment, ProviderWebhookEvent, SellerPaymentAccount, Settlement
from .review_fixes import requeue_failed_transfer
from .services import approve_commerce_payment, finalize_order_refund
from .webhooks import _record_chargeback_recovery, _restore_order_stock


def _webhook_secret() -> str:
    return (
        getattr(settings, "STRIPE_WEBHOOK_SECRET", "")
        or os.getenv("STRIPE_WEBHOOK_SECRET", "")
    ).strip()


def _signature_is_valid(raw: bytes, header: str) -> bool:
    secret = _webhook_secret()
    if not secret or not header:
        return False

    timestamp = ""
    signatures: list[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1" and value:
            signatures.append(value)
    if not timestamp or not signatures:
        return False

    try:
        event_time = int(timestamp)
    except ValueError:
        return False
    tolerance = int(
        getattr(
            settings,
            "STRIPE_WEBHOOK_TOLERANCE_SECONDS",
            os.getenv("STRIPE_WEBHOOK_TOLERANCE_SECONDS", "300"),
        )
        or 300
    )
    if abs(int(time.time()) - event_time) > tolerance:
        return False

    try:
        body = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    signed = f"{timestamp}.{body}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, signature) for signature in signatures)


def _marketlift_order_id(data: dict) -> str:
    return str((data.get("metadata") or {}).get("marketlift_order_id") or "").strip()


def _find_payment(data: dict, object_type: str) -> CommercePayment | None:
    data_id = str(data.get("id") or "").strip()
    payment_intent = str(data.get("payment_intent") or "").strip()
    qs = CommercePayment.objects.select_related("order", "order__listing", "order__buyer")

    if object_type == "checkout.session" and data_id:
        payment = qs.filter(provider="stripe", provider_order_id=data_id).first()
        if payment:
            return payment
    if object_type == "payment_intent" and data_id:
        payment = qs.filter(provider="stripe", provider_transaction_id=data_id).first()
        if payment:
            return payment
    if object_type in {"charge", "refund"} and data_id:
        payment = qs.filter(provider="stripe", provider_charge_id=data_id).first()
        if payment:
            return payment
    charge = data.get("charge")
    if isinstance(charge, dict):
        charge = charge.get("id")
    charge = str(charge or "").strip()
    if charge:
        payment = qs.filter(provider="stripe", provider_charge_id=charge).first()
        if payment:
            return payment
    if payment_intent:
        payment = qs.filter(
            provider="stripe", provider_transaction_id=payment_intent
        ).first()
        if payment:
            return payment

    local_order_id = _marketlift_order_id(data)
    if local_order_id:
        return (
            qs.filter(order_id=local_order_id, provider="stripe")
            .order_by("-created_at")
            .first()
        )
    return None


def _sync_payment_references(
    payment: CommercePayment, data: dict, object_type: str
) -> None:
    changed: list[str] = []
    data_id = str(data.get("id") or "").strip()

    if object_type == "checkout.session":
        if data_id and not payment.provider_order_id:
            payment.provider_order_id = data_id
            changed.append("provider_order_id")
        payment_intent = str(data.get("payment_intent") or "").strip()
        if payment_intent and not payment.provider_transaction_id:
            payment.provider_transaction_id = payment_intent
            changed.append("provider_transaction_id")
        checkout_url = str(data.get("url") or "").strip()
        if checkout_url:
            checkout_data = dict(payment.checkout_data or {})
            checkout_data["checkout_url"] = checkout_url
            payment.checkout_data = checkout_data
            changed.append("checkout_data")
    elif object_type == "payment_intent":
        if data_id and not payment.provider_transaction_id:
            payment.provider_transaction_id = data_id
            changed.append("provider_transaction_id")
        latest_charge = data.get("latest_charge")
        if isinstance(latest_charge, dict):
            latest_charge = latest_charge.get("id")
        latest_charge = str(latest_charge or "").strip()
        if latest_charge and not payment.provider_charge_id:
            payment.provider_charge_id = latest_charge
            changed.append("provider_charge_id")
    elif object_type == "charge":
        if data_id and not payment.provider_charge_id:
            payment.provider_charge_id = data_id
            changed.append("provider_charge_id")
        payment_intent = data.get("payment_intent")
        if isinstance(payment_intent, dict):
            payment_intent = payment_intent.get("id")
        payment_intent = str(payment_intent or "").strip()
        if payment_intent and not payment.provider_transaction_id:
            payment.provider_transaction_id = payment_intent
            changed.append("provider_transaction_id")

    if changed:
        payment.save(update_fields=tuple(changed + ["updated_at"]))


def _fail_pending_payment(
    payment: CommercePayment, *, status: str, cancelled: bool = False, message: str = ""
) -> None:
    if payment.status != CommercePayment.Status.PENDING:
        return
    payment.status = (
        CommercePayment.Status.CANCELLED if cancelled else CommercePayment.Status.FAILED
    )
    payment.provider_status = status
    payment.failure_message = message[:1000]
    payment.save(
        update_fields=(
            "status",
            "provider_status",
            "failure_message",
            "updated_at",
        )
    )
    _restore_order_stock(payment)


def _sync_connect_account(data: dict) -> None:
    account_id = str(data.get("id") or "").strip()
    if not account_id:
        return
    account = (
        SellerPaymentAccount.objects.select_for_update()
        .select_related("seller")
        .filter(provider="stripe", provider_recipient_id=account_id)
        .first()
    )
    if not account:
        return

    requirements = data.get("requirements") or {}
    disabled_reason = str(requirements.get("disabled_reason") or "").strip()
    details_submitted = bool(data.get("details_submitted"))
    payouts_enabled = bool(data.get("payouts_enabled"))
    if payouts_enabled and details_submitted:
        status = SellerPaymentAccount.Status.ACTIVE
    elif disabled_reason:
        status = SellerPaymentAccount.Status.RESTRICTED
    else:
        status = SellerPaymentAccount.Status.PENDING

    account.status = status
    account.payouts_enabled = status == SellerPaymentAccount.Status.ACTIVE
    if account.payouts_enabled:
        account.kyc_url = ""
    account.metadata = {
        **(account.metadata or {}),
        "provider_status": status,
        "details_submitted": details_submitted,
        "charges_enabled": bool(data.get("charges_enabled")),
        "payouts_enabled": payouts_enabled,
        "requirements": requirements,
    }
    account.save(
        update_fields=(
            "status",
            "payouts_enabled",
            "kyc_url",
            "metadata",
            "updated_at",
        )
    )

    seller = account.seller
    if account.payouts_enabled and not seller.verified:
        seller.verified_at = timezone.now()
        seller.save(update_fields=("verified_at", "updated_at"))


@transaction.atomic
def process_stripe_event(payload: dict, raw: bytes) -> bool:
    event_id = str(payload.get("id") or "").strip()
    event_type = str(payload.get("type") or "").strip()
    if not event_id:
        event_id = f"{event_type}:{hashlib.sha256(raw).hexdigest()}"

    event, created = ProviderWebhookEvent.objects.get_or_create(
        provider="stripe",
        provider_event_id=event_id,
        defaults={
            "event_type": event_type,
            "payload_hash": hashlib.sha256(raw).hexdigest(),
        },
    )
    if not created and event.processed_at:
        return False

    data = ((payload.get("data") or {}).get("object") or {})
    if not isinstance(data, dict):
        data = {}
    object_type = str(data.get("object") or "")

    if event_type == "account.updated":
        _sync_connect_account(data)

    payment = _find_payment(data, object_type)
    if payment:
        _sync_payment_references(payment, data, object_type)

        if event_type in {
            "checkout.session.completed",
            "checkout.session.async_payment_succeeded",
        }:
            provider_status = str(data.get("payment_status") or "paid").lower()
            payment.provider_status = provider_status
            payment.save(update_fields=("provider_status", "updated_at"))
            if provider_status == "paid" or event_type.endswith("async_payment_succeeded"):
                approve_commerce_payment(payment)

        elif event_type == "payment_intent.succeeded":
            payment.provider_status = "succeeded"
            payment.save(update_fields=("provider_status", "updated_at"))
            approve_commerce_payment(payment)

        elif event_type == "payment_intent.payment_failed":
            # A card decline inside hosted Checkout is not terminal: Stripe can
            # keep the Session open so the buyer can try another card.
            error = data.get("last_payment_error") or {}
            payment.provider_status = "payment_failed_retryable"
            payment.failure_message = str(error.get("message") or "")[:1000]
            payment.save(
                update_fields=(
                    "provider_status",
                    "failure_message",
                    "updated_at",
                )
            )

        elif event_type in {
            "checkout.session.expired",
            "checkout.session.async_payment_failed",
            "payment_intent.canceled",
        }:
            error = data.get("last_payment_error") or {}
            message = str(error.get("message") or "")
            _fail_pending_payment(
                payment,
                status=event_type,
                cancelled=event_type
                in {"checkout.session.expired", "payment_intent.canceled"},
                message=message,
            )

        elif event_type == "charge.refunded":
            amount = int(data.get("amount") or 0)
            refunded = int(data.get("amount_refunded") or 0)
            if amount and refunded < amount:
                payment.status = CommercePayment.Status.PARTIALLY_REFUNDED
                payment.provider_status = "partially_refunded"
                payment.save(update_fields=("status", "provider_status", "updated_at"))
            else:
                finalize_order_refund(
                    payment=payment,
                    reason="Stripe charge.refunded webhook",
                    provider_status="refunded",
                )

        elif event_type == "charge.dispute.created":
            payment.status = CommercePayment.Status.CHARGEBACK
            payment.provider_status = "disputed"
            payment.save(update_fields=("status", "provider_status", "updated_at"))
            _record_chargeback_recovery(payment, event_type)

    if event_type.startswith("transfer."):
        transfer_id = str(data.get("id") or "").strip()
        if transfer_id and event_type in {"transfer.reversed", "transfer.failed"}:
            requeue_failed_transfer(transfer_id=transfer_id)
        elif transfer_id and event_type == "transfer.created":
            now = timezone.now()
            Settlement.objects.select_for_update().filter(
                provider_transfer_id=transfer_id,
                status=Settlement.Status.PAYOUT_REQUESTED,
            ).update(status=Settlement.Status.PAID, paid_at=now, updated_at=now)

    event.processed_at = timezone.now()
    event.save(update_fields=("processed_at", "updated_at"))
    return True


@csrf_exempt
def stripe_webhook(request: HttpRequest):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed."}, status=405)

    raw = request.body
    signature = request.headers.get("Stripe-Signature", "")
    if not _signature_is_valid(raw, signature):
        return JsonResponse({"detail": "Invalid Stripe signature."}, status=400)

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"detail": "Invalid webhook payload."}, status=400)

    process_stripe_event(payload, raw)
    return JsonResponse({"received": True})
