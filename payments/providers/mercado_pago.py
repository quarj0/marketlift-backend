from __future__ import annotations

from decimal import Decimal
import httpx
from django.conf import settings

from .base import BasePaymentProvider, PaymentProviderError, ProviderResult


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _extract(data: dict) -> ProviderResult:
    txs = (data.get("transactions") or {}).get("payments") or []
    tx = txs[0] if txs else {}
    method = tx.get("payment_method") or {}
    checkout = {
        key: method.get(key)
        for key in ("ticket_url", "qr_code", "qr_code_base64", "barcode_content")
        if method.get(key)
    }
    return ProviderResult(
        order_id=str(data.get("id") or ""),
        payment_id=str(tx.get("id") or ""),
        status=str(data.get("status") or tx.get("status") or ""),
        status_detail=str(data.get("status_detail") or tx.get("status_detail") or ""),
        checkout_data=checkout,
    )


class MercadoPagoProvider(BasePaymentProvider):
    name = "mercado_pago"
    api_url = "https://api.mercadopago.com/v1/orders"

    def _headers(self, idempotency_key: str | None = None):
        token = getattr(settings, "MERCADO_PAGO_ACCESS_TOKEN", "")
        if not token:
            raise PaymentProviderError("MERCADO_PAGO_ACCESS_TOKEN is not configured.")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if idempotency_key:
            headers["X-Idempotency-Key"] = idempotency_key
        return headers

    def create_order(
        self, *, payment, payer: dict, card: dict | None = None
    ) -> ProviderResult:
        method = {}
        if payment.method == "pix":
            method = {"id": "pix", "type": "bank_transfer"}
        elif payment.method == "boleto":
            method = {"id": "boleto", "type": "ticket"}
        elif payment.method == "card":
            card = card or {}
            required = ["token", "payment_method_id"]
            missing = [key for key in required if not card.get(key)]
            if missing:
                raise PaymentProviderError(
                    "Card payments require a Mercado Pago card token and payment method id."
                )
            method = {
                "id": card["payment_method_id"],
                "type": card.get("payment_type") or "credit_card",
                "token": card["token"],
                "installments": int(card.get("installments") or 1),
            }
        else:
            raise PaymentProviderError("Unsupported payment method.")

        amount = _money(payment.amount)
        payload = {
            "type": "online",
            "processing_mode": "automatic",
            "total_amount": amount,
            "external_reference": payment.reference,
            "description": (
                "Marketlift seller plan"
                if payment.purpose == "subscription"
                else "Marketlift listing promotion"
            ),
            "payer": payer,
            "transactions": {
                "payments": [{"amount": amount, "payment_method": method}]
            },
        }
        try:
            response = httpx.post(
                self.api_url,
                headers=self._headers(payment.idempotency_key),
                json=payload,
                timeout=20.0,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                detail = exc.response.json()
            except Exception:
                detail = exc.response.text
            raise PaymentProviderError(
                f"Mercado Pago rejected the order: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise PaymentProviderError("Could not reach Mercado Pago.") from exc
        return _extract(response.json())

    def get_order(self, order_id: str) -> ProviderResult:
        try:
            response = httpx.get(
                f"{self.api_url}/{order_id}", headers=self._headers(), timeout=20.0
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PaymentProviderError(
                "Could not retrieve the Mercado Pago order."
            ) from exc
        return _extract(response.json())
