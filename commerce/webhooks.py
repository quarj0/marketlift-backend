from __future__ import annotations

import hashlib
import hmac
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import (
    CommercePayment,
    Dispute,
    Order,
    ProviderWebhookEvent,
    SellerPaymentAccount,
    Settlement,
)
from .policy_models import ListingCommerceSettings
from .review_fixes import requeue_failed_transfer
from .services import approve_commerce_payment, finalize_order_refund


def _event_identity(payload: dict, raw: bytes) -> tuple[str, str, str]:
    digest = hashlib.sha256(raw).hexdigest()
    event_type = str(payload.get("type") or payload.get("event") or "")
    event_id = str(payload.get("id") or "").strip()
    if not event_id:
        data = payload.get("data") or {}
        event_id = f"{event_type}:{data.get('id') or digest}"
    return event_id, event_type, digest


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


def _marketlift_order_id(data: dict) -> str:
    metadata = data.get("metadata") or {}
    nested_order = data.get("order") or {}
    nested_metadata = nested_order.get("metadata") or {}
    return str(
        metadata.get("marketlift_order_id")
        or nested_metadata.get("marketlift_order_id")
        or ""
    ).strip()


def _find_payment(data: dict) -> CommercePayment | None:
    data_id = str(data.get("id") or "")
    order = data.get("order") or {}
    order_id = str(order.get("id") or data.get("order_id") or "")
    qs = CommercePayment.objects.select_related(
        "order", "order__listing", "order__buyer"
    )
    if data_id:
        payment = qs.filter(provider_charge_id=data_id).first()
        if payment:
            return payment
        payment = qs.filter(provider_order_id=data_id).first()
        if payment:
            return payment
    if order_id:
        payment = qs.filter(provider_order_id=order_id).first()
        if payment:
            return payment

    # If the provider accepted checkout but Marketlift lost the HTTP response,
    # provider ids have not yet been persisted. The request metadata is durable
    # at Pagar.me and lets the webhook recover the exact local order/payment.
    local_order_id = _marketlift_order_id(data)
    if local_order_id:
        try:
            return qs.filter(order_id=local_order_id).order_by("-created_at").first()
        except (ValidationError, ValueError):
            return None
    return None


def _sync_payment_provider_references(
    payment: CommercePayment, data: dict, event_type: str
) -> None:
    lowered = event_type.lower()
    data_id = str(data.get("id") or "").strip()
    nested_order = data.get("order") or {}
    nested_order_id = str(
        nested_order.get("id") or data.get("order_id") or ""
    ).strip()
    charges = data.get("charges") or []
    charge = charges[0] if charges else {}
    last_tx = data.get("last_transaction") or charge.get("last_transaction") or {}

    changed: list[str] = []
    if "order" in lowered and data_id and not payment.provider_order_id:
        payment.provider_order_id = data_id
        changed.append("provider_order_id")
    elif nested_order_id and not payment.provider_order_id:
        payment.provider_order_id = nested_order_id
        changed.append("provider_order_id")

    charge_id = str(charge.get("id") or "").strip()
    if not charge_id and "charge" in lowered:
        charge_id = data_id
    if charge_id and not payment.provider_charge_id:
        payment.provider_charge_id = charge_id
        changed.append("provider_charge_id")

    transaction_id = str(last_tx.get("id") or "").strip()
    if transaction_id and not payment.provider_transaction_id:
        payment.provider_transaction_id = transaction_id
        changed.append("provider_transaction_id")

    if changed:
        changed.append("updated_at")
        payment.save(update_fields=tuple(changed))


def _recipient_status(status: str) -> tuple[str, bool]:
    normalized = status.lower().strip()
    if normalized in {"active", "enabled", "registered"}:
        return SellerPaymentAccount.Status.ACTIVE, True
    if normalized in {
        "rejected",
        "refused",
        "denied",
        "failed",
        "canceled",
        "cancelled",
    }:
        return SellerPaymentAccount.Status.REJECTED, False
    if normalized in {
        "restricted",
        "blocked",
        "suspended",
        "disabled",
        "inactive",
    }:
        return SellerPaymentAccount.Status.RESTRICTED, False
    return SellerPaymentAccount.Status.PENDING, False


def _record_chargeback_recovery(payment: CommercePayment, event_type: str) -> None:
    order = Order.objects.select_for_update().select_related("buyer").get(
        pk=payment.order_id
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
                "Payment provider reported a chargeback. Fulfillment is blocked "
                f"pending financial review ({event_type})."
            ),
            evidence=[{"source": "payment_provider", "event_type": event_type}],
        )


@transaction.atomic
def process_pagarme_event(payload: dict, raw: bytes) -> bool:
    event_id, event_type, digest = _event_identity(payload, raw)
    event, created = ProviderWebhookEvent.objects.get_or_create(
        provider="pagarme",
        provider_event_id=event_id,
        defaults={"event_type": event_type, "payload_hash": digest},
    )
    if not created and event.processed_at:
        return False

    data = payload.get("data") or {}
    lowered = event_type.lower()

    if "recipient" in lowered:
        recipient_id = str(data.get("id") or "")
        account = SellerPaymentAccount.objects.filter(
            provider_recipient_id=recipient_id
        ).first()
        if account:
            provider_status = str(data.get("status") or "").lower()
            account_status, payouts_enabled = _recipient_status(provider_status)
            account.status = account_status
            account.payouts_enabled = payouts_enabled
            account.metadata = {
                **account.metadata,
                "provider_status": provider_status,
            }
            account.save(
                update_fields=(
                    "status",
                    "payouts_enabled",
                    "metadata",
                    "updated_at",
                )
            )

    payment = _find_payment(data)
    if payment:
        _sync_payment_provider_references(payment, data, event_type)
        if "refund" in lowered:
            finalize_order_refund(
                payment=payment,
                reason=f"Pagar.me webhook: {event_type}",
                provider_status=str(data.get("status") or event_type),
            )
        elif "chargeback" in lowered:
            payment.status = CommercePayment.Status.CHARGEBACK
            payment.provider_status = str(data.get("status") or event_type)
            payment.save(update_fields=("status", "provider_status", "updated_at"))
            _record_chargeback_recovery(payment, event_type)
        elif any(
            marker in lowered
            for marker in ("paid", "payment_succeeded", "approved")
        ):
            payment.provider_status = str(data.get("status") or "paid")
            payment.save(update_fields=("provider_status", "updated_at"))
            approve_commerce_payment(payment)
        elif any(
            marker in lowered
            for marker in ("failed", "canceled", "cancelled", "declined", "refused")
        ):
            if payment.status == CommercePayment.Status.PENDING:
                provider_status = str(data.get("status") or event_type)
                payment.status = (
                    CommercePayment.Status.CANCELLED
                    if any(marker in lowered for marker in ("canceled", "cancelled"))
                    else CommercePayment.Status.FAILED
                )
                payment.provider_status = provider_status
                payment.failure_message = str(
                    data.get("last_transaction", {}).get("acquirer_message") or ""
                )
                payment.save(
                    update_fields=(
                        "status",
                        "provider_status",
                        "failure_message",
                        "updated_at",
                    )
                )
                _restore_order_stock(payment)

    if "transfer" in lowered:
        transfer_id = str(data.get("id") or "")
        status = str(data.get("status") or "").lower()
        if transfer_id and status in {
            "paid",
            "transferred",
            "completed",
            "success",
            "succeeded",
        }:
            rows = Settlement.objects.select_for_update().filter(
                provider_transfer_id=transfer_id,
                status=Settlement.Status.PAYOUT_REQUESTED,
            )
            now = timezone.now()
            rows.update(status=Settlement.Status.PAID, paid_at=now, updated_at=now)
        elif transfer_id and status in {
            "failed",
            "refused",
            "rejected",
            "canceled",
            "cancelled",
        }:
            requeue_failed_transfer(transfer_id=transfer_id)

    event.processed_at = timezone.now()
    event.save(update_fields=("processed_at", "updated_at"))
    return True


@csrf_exempt
def pagarme_webhook(request: HttpRequest, token: str):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed."}, status=405)
    expected = getattr(settings, "PAGARME_WEBHOOK_TOKEN", "")
    if not expected or not hmac.compare_digest(token, expected):
        return JsonResponse({"detail": "Not found."}, status=404)
    raw = request.body
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"detail": "Invalid webhook payload."}, status=400)
    process_pagarme_event(payload, raw)
    return JsonResponse({"received": True})
