from __future__ import annotations

import hashlib
import os

import stripe
from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import CommercePayment, ProviderWebhookEvent, SellerPaymentAccount, Settlement
from .providers.base import CommerceProviderError
from .providers.stripe import StripeCommerceProvider
from .review_fixes import requeue_failed_transfer
from .services import approve_commerce_payment, finalize_order_refund
from .stripe_runtime import _apply_stripe_account_snapshot
from .webhooks import _record_chargeback_recovery, _restore_order_stock


V2_CONNECT_EVENT_TYPES = {
    "v2.core.account[requirements].updated",
    "v2.core.account[configuration.recipient].capability_status_updated",
}


def _webhook_secret() -> str:
    return (
        getattr(settings, "STRIPE_WEBHOOK_SECRET", "")
        or os.getenv("STRIPE_WEBHOOK_SECRET", "")
    ).strip()


def _connect_webhook_secret() -> str:
    return (
        getattr(settings, "STRIPE_CONNECT_WEBHOOK_SECRET", "")
        or os.getenv("STRIPE_CONNECT_WEBHOOK_SECRET", "")
    ).strip()


def _webhook_tolerance() -> int:
    return int(
        getattr(
            settings,
            "STRIPE_WEBHOOK_TOLERANCE_SECONDS",
            os.getenv("STRIPE_WEBHOOK_TOLERANCE_SECONDS", "300"),
        )
        or 300
    )


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
            provider="stripe",
            provider_transaction_id=payment_intent,
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
    payment: CommercePayment,
    data: dict,
    object_type: str,
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
    payment: CommercePayment,
    *,
    status: str,
    cancelled: bool = False,
    message: str = "",
) -> None:
    if payment.status != CommercePayment.Status.PENDING:
        return
    payment.status = (
        CommercePayment.Status.CANCELLED
        if cancelled
        else CommercePayment.Status.FAILED
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
    """Apply a live Accounts v2 snapshot to the Marketlift seller mapping."""
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
    _apply_stripe_account_snapshot(account, data)


@transaction.atomic
def process_stripe_connect_event(
    *,
    event_id: str,
    event_type: str,
    account_data: dict,
    raw: bytes,
) -> bool:
    """Process the two thin Accounts v2 events Marketlift subscribes to."""
    normalized_id = str(event_id or "").strip()
    if not normalized_id:
        normalized_id = f"{event_type}:{hashlib.sha256(raw).hexdigest()}"

    event, created = ProviderWebhookEvent.objects.get_or_create(
        provider="stripe",
        provider_event_id=normalized_id,
        defaults={
            "event_type": event_type,
            "payload_hash": hashlib.sha256(raw).hexdigest(),
        },
    )
    if not created and event.processed_at:
        return False

    if event_type in V2_CONNECT_EVENT_TYPES:
        _sync_connect_account(account_data)

    event.processed_at = timezone.now()
    event.save(update_fields=("processed_at", "updated_at"))
    return True


@transaction.atomic
def process_stripe_event(payload: dict, raw: bytes) -> bool:
    """Process Stripe v1 snapshot events for checkout and money movement."""
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
            if (
                provider_status == "paid"
                or event_type.endswith("async_payment_succeeded")
            ):
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
            _fail_pending_payment(
                payment,
                status=event_type,
                cancelled=event_type
                in {
                    "checkout.session.expired",
                    "payment_intent.canceled",
                },
                message=str(error.get("message") or ""),
            )

        elif event_type == "charge.refunded":
            amount = int(data.get("amount") or 0)
            refunded = int(data.get("amount_refunded") or 0)
            if amount and refunded < amount:
                payment.status = CommercePayment.Status.PARTIALLY_REFUNDED
                payment.provider_status = "partially_refunded"
                payment.save(
                    update_fields=("status", "provider_status", "updated_at")
                )
            else:
                finalize_order_refund(
                    payment=payment,
                    reason="Stripe charge.refunded webhook",
                    provider_status="refunded",
                )

        elif event_type == "charge.dispute.created":
            payment.status = CommercePayment.Status.CHARGEBACK
            payment.provider_status = "disputed"
            payment.save(
                update_fields=("status", "provider_status", "updated_at")
            )
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
            ).update(
                status=Settlement.Status.PAID,
                paid_at=now,
                updated_at=now,
            )

    event.processed_at = timezone.now()
    event.save(update_fields=("processed_at", "updated_at"))
    return True


def _provider_or_error() -> tuple[StripeCommerceProvider | None, JsonResponse | None]:
    try:
        return StripeCommerceProvider(), None
    except CommerceProviderError as exc:
        return None, JsonResponse({"detail": str(exc)}, status=503)


@csrf_exempt
def stripe_webhook(request: HttpRequest):
    """Receive Stripe v1 snapshot events for buyer payments and transfers."""
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed."}, status=405)

    secret = _webhook_secret()
    if not secret:
        # PLACEHOLDER: copy the signing secret for the normal Stripe webhook
        # destination into STRIPE_WEBHOOK_SECRET.
        return JsonResponse(
            {
                "detail": (
                    "STRIPE_WEBHOOK_SECRET is not configured for the Stripe "
                    "payment webhook destination."
                )
            },
            status=503,
        )

    provider, error_response = _provider_or_error()
    if error_response is not None:
        return error_response

    raw = request.body
    signature = request.headers.get("Stripe-Signature", "")
    try:
        event = provider.stripe_client.construct_event(
            raw,
            signature,
            secret,
            tolerance=_webhook_tolerance(),
        )
    except (ValueError, stripe.SignatureVerificationError):
        return JsonResponse({"detail": "Invalid Stripe signature or payload."}, status=400)

    process_stripe_event(event.to_dict(), raw)
    return JsonResponse({"received": True})


@csrf_exempt
def stripe_connect_webhook(request: HttpRequest):
    """Receive thin Accounts v2 requirement/capability events.

    Stripe requires thin payloads for Accounts v2. We verify and parse the thin
    notification with StripeClient, retrieve the full event, then retrieve the
    current Account v2 object with the exact include fields Marketlift needs.
    """
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed."}, status=405)

    secret = _connect_webhook_secret()
    if not secret:
        # PLACEHOLDER: create a second Stripe Event Destination using Thin
        # payloads and store its signing secret in STRIPE_CONNECT_WEBHOOK_SECRET.
        return JsonResponse(
            {
                "detail": (
                    "STRIPE_CONNECT_WEBHOOK_SECRET is not configured for the "
                    "Accounts v2 thin-event destination."
                )
            },
            status=503,
        )

    provider, error_response = _provider_or_error()
    if error_response is not None:
        return error_response

    raw = request.body
    signature = request.headers.get("Stripe-Signature", "")
    try:
        thin_event = provider.stripe_client.parse_event_notification(
            raw,
            signature,
            secret,
            tolerance=_webhook_tolerance(),
        )
        if thin_event.type not in V2_CONNECT_EVENT_TYPES:
            return JsonResponse({"received": True, "ignored": True})

        # Fetch the full V2 event so Stripe can supply context/change details,
        # then fetch the live account state rather than trusting a stale payload.
        full_event = thin_event.fetch_event()
        related_object = getattr(thin_event, "related_object", None)
        account_id = str(getattr(related_object, "id", "") or "").strip()
        if not account_id:
            related_object = getattr(full_event, "related_object", None)
            account_id = str(getattr(related_object, "id", "") or "").strip()
        if not account_id:
            return JsonResponse(
                {"detail": "Stripe thin event did not reference an account."},
                status=400,
            )

        account_data = provider.get_recipient(account_id)
    except (ValueError, stripe.SignatureVerificationError):
        return JsonResponse({"detail": "Invalid Stripe thin-event signature or payload."}, status=400)
    except (stripe.StripeError, CommerceProviderError) as exc:
        return JsonResponse(
            {"detail": f"Stripe event retrieval failed: {exc}"},
            status=502,
        )

    process_stripe_connect_event(
        event_id=thin_event.id,
        event_type=thin_event.type,
        account_data=account_data,
        raw=raw,
    )
    return JsonResponse({"received": True})
