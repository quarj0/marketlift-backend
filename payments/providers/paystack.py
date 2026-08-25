from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import httpx
from django.conf import settings

from marketlift.markets.profiles import get_market_profile

from .base import BasePaymentProvider, PaymentProviderError, ProviderResult


_METHOD_CHANNEL = {
    "card": "card",
    "mobile_money": "mobile_money",
    "bank_transfer": "bank_transfer",
    "ussd": "ussd",
    "eft": "eft",
}


def _profile_for_currency(currency: str):
    currency = (currency or "").upper()
    for profile in settings.MARKETLIFT_ENABLED_MARKETS:
        if profile.currency == currency:
            return profile
    # A one-market deployment can still verify historical rows after changing
    # MARKETLIFT_ENABLED_MARKETS by resolving the current profile directly.
    current = get_market_profile(settings.MARKETLIFT_MARKET_CODE)
    if current.currency == currency:
        return current
    raise PaymentProviderError(f"Paystack currency {currency!r} is not configured.")


def _subunit(amount: Decimal, currency: str) -> int:
    profile = _profile_for_currency(currency)
    value = (Decimal(amount) * profile.currency_subunit_factor).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(value)


def _major_amount(value: Any, currency: str) -> Decimal | None:
    if value in (None, ""):
        return None
    profile = _profile_for_currency(currency)
    try:
        return (Decimal(str(value)) / Decimal(profile.currency_subunit_factor)).quantize(
            Decimal("0.01")
        )
    except Exception:
        return None


def _extract_verified(data: dict) -> ProviderResult:
    row = data.get("data") if isinstance(data.get("data"), dict) else data
    currency = str(row.get("currency") or "").upper()
    reference = str(row.get("reference") or "")
    return ProviderResult(
        order_id=reference,
        payment_id=str(row.get("id") or ""),
        status=str(row.get("status") or ""),
        status_detail=str(row.get("gateway_response") or row.get("message") or ""),
        checkout_data={
            key: row.get(key)
            for key in ("reference", "paid_at", "channel")
            if row.get(key) not in (None, "")
        },
        amount=_major_amount(row.get("amount"), currency) if currency else None,
        currency=currency,
    )


class PaystackProvider(BasePaymentProvider):
    """Paystack Checkout provider for Marketlift service payments.

    This integration only charges sellers for Marketlift plans/promotions. It is
    deliberately not a buyer -> seller marketplace payment/split implementation.
    """

    name = "paystack"

    @property
    def base_url(self) -> str:
        return getattr(settings, "PAYSTACK_API_BASE_URL", "https://api.paystack.co").rstrip("/")

    def _headers(self) -> dict[str, str]:
        secret = getattr(settings, "PAYSTACK_SECRET_KEY", "").strip()
        if not secret:
            raise PaymentProviderError("PAYSTACK_SECRET_KEY is not configured.")
        return {
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, *, json: dict | None = None) -> dict:
        try:
            with httpx.Client(timeout=20.0, follow_redirects=False) as client:
                response = client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=self._headers(),
                    json=json,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            try:
                detail = exc.response.json()
            except Exception:
                detail = exc.response.text
            raise PaymentProviderError(f"Paystack rejected the request: {detail}") from exc
        except httpx.HTTPError as exc:
            raise PaymentProviderError("Could not reach Paystack.") from exc
        except ValueError as exc:
            raise PaymentProviderError("Paystack returned an invalid response.") from exc
        if not isinstance(payload, dict) or payload.get("status") is False:
            raise PaymentProviderError(
                str((payload or {}).get("message") or "Paystack rejected the request.")
            )
        return payload

    def create_order(
        self, *, payment, payer: dict, card: dict | None = None
    ) -> ProviderResult:
        channel = _METHOD_CHANNEL.get(payment.method)
        if not channel:
            raise PaymentProviderError(
                f"Payment method {payment.method!r} is not supported by Paystack checkout."
            )
        email = str((payer or {}).get("email") or payment.user.email or "").strip()
        if not email:
            raise PaymentProviderError("Paystack checkout requires a payer email address.")

        payload: dict[str, Any] = {
            "email": email,
            "amount": str(_subunit(payment.amount, payment.currency)),
            "currency": payment.currency,
            "reference": payment.reference,
            "channels": [channel],
            "metadata": json.dumps(
                {
                    "marketlift_payment_id": str(payment.id),
                    "purpose": payment.purpose,
                    "seller_id": str(payment.seller_id),
                },
                separators=(",", ":"),
            ),
        }
        callback_url = getattr(settings, "PAYSTACK_CALLBACK_URL", "").strip()
        if callback_url:
            payload["callback_url"] = callback_url

        response = self._request("POST", "/transaction/initialize", json=payload)
        row = response.get("data") or {}
        reference = str(row.get("reference") or payment.reference)
        return ProviderResult(
            order_id=reference,
            status="pending",
            status_detail=str(response.get("message") or "Authorization URL created"),
            checkout_data={
                key: row.get(key)
                for key in ("authorization_url", "access_code", "reference")
                if row.get(key)
            },
            amount=Decimal(payment.amount),
            currency=payment.currency,
        )

    def get_order(self, order_id: str) -> ProviderResult:
        reference = str(order_id or "").strip()
        if not reference:
            raise PaymentProviderError("Paystack transaction reference is required.")
        response = self._request("GET", f"/transaction/verify/{reference}")
        return _extract_verified(response)
