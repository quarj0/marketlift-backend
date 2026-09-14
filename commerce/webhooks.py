from __future__ import annotations

import hashlib
import hmac
import json

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import CommercePayment, ProviderWebhookEvent, SellerPaymentAccount, Settlement
from .policy_models import ListingCommerceSettings
from .services import approve_commerce_payment


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
        config = ListingCommerceSettings.objects.select_for_update().get(listing=order.listing)
    except ListingCommerceSettings.DoesNotExist:
        return
    config.stock_quantity += order.quantity
    config.save(update_fields=("stock_quantity", "updated_at"))
    order.status = order.Status.CANCELLED
    order.cancelled_at = timezone.now()
    order.save(update_fields=("status", "cancelled_at", "updated_at"))


def _find_payment(data: dict) -> CommercePayment | None:
    data_id = str(data.get("id") or "")
    order = data.get("order") or {}
    order_id = str(order.get("id") or data.get("order_id") or "")
    qs = CommercePayment.objects.select_related("order", "order__listing")
    if data_id:
        payment = qs.filter(provider_charge_id=data_id).first()
        if payment:
            return payment
    if order_id:
        return qs.filter(provider_order_id=order_id).first()
    return None


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
        account = SellerPaymentAccount.objects.filter(provider_recipient_id=recipient_id).first()
        if account:
            status = str(data.get("status") or "").lower()
            active = status in {"active", "enabled", "registered"}
            account.status = (
                SellerPaymentAccount.Status.ACTIVE
                if active
                else SellerPaymentAccount.Status.PENDING
            )
            account.payouts_enabled = active
            account.metadata = {**account.metadata, "provider_status": status}
            account.save(update_fields=("status", "payouts_enabled", "metadata", "updated_at"))

    payment = _find_payment(data)
    if payment:
        if any(marker in lowered for marker in ("paid", "payment_succeeded", "approved")):
            payment.provider_status = str(data.get("status") or "paid")
            payment.save(update_fields=("provider_status", "updated_at"))
            approve_commerce_payment(payment)
        elif any(marker in lowered for marker in ("failed", "canceled", "cancelled")):
            if payment.status == CommercePayment.Status.PENDING:
                payment.status = CommercePayment.Status.FAILED
                payment.provider_status = str(data.get("status") or event_type)
                payment.failure_message = str(data.get("last_transaction", {}).get("acquirer_message") or "")
                payment.save(update_fields=("status", "provider_status", "failure_message", "updated_at"))
                _restore_order_stock(payment)
        elif "refund" in lowered:
            payment.status = CommercePayment.Status.REFUNDED
            payment.refunded_at = timezone.now()
            payment.provider_status = str(data.get("status") or event_type)
            payment.save(update_fields=("status", "refunded_at", "provider_status", "updated_at"))
        elif "chargeback" in lowered:
            payment.status = CommercePayment.Status.CHARGEBACK
            payment.provider_status = str(data.get("status") or event_type)
            payment.save(update_fields=("status", "provider_status", "updated_at"))
            settlement = Settlement.objects.select_for_update().filter(order=payment.order).first()
            if settlement and settlement.status != Settlement.Status.PAID:
                settlement.status = Settlement.Status.BLOCKED
                settlement.save(update_fields=("status", "updated_at"))

    if "transfer" in lowered:
        transfer_id = str(data.get("id") or "")
        status = str(data.get("status") or "").lower()
        if transfer_id and status in {"paid", "transferred", "completed"}:
            rows = Settlement.objects.select_for_update().filter(
                provider_transfer_id=transfer_id,
                status=Settlement.Status.PAYOUT_REQUESTED,
            )
            now = timezone.now()
            rows.update(status=Settlement.Status.PAID, paid_at=now, updated_at=now)

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
