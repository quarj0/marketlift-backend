from __future__ import annotations

import os

import httpx
from django.conf import settings

from .base import CommerceProvider, CommerceProviderError


def _form_rows(value, prefix: str = "") -> list[tuple[str, str]]:
    """Flatten nested dictionaries/lists into Stripe's form-encoded bracket syntax."""
    rows: list[tuple[str, str]] = []
    if value is None:
        return rows
    if isinstance(value, bool):
        return [(prefix, "true" if value else "false")]
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{prefix}[{key}]" if prefix else str(key)
            rows.extend(_form_rows(item, child))
        return rows
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            if isinstance(item, (dict, list, tuple)):
                child = f"{prefix}[{index}]"
            else:
                child = f"{prefix}[]"
            rows.extend(_form_rows(item, child))
        return rows
    return [(prefix, str(value))]


class StripeCommerceProvider(CommerceProvider):
    code = "stripe"

    def __init__(self):
        self.secret_key = (getattr(settings, "STRIPE_SECRET_KEY", "") or os.getenv("STRIPE_SECRET_KEY", "")).strip()
        self.base_url = getattr(
            settings, "STRIPE_API_BASE_URL", os.getenv("STRIPE_API_BASE_URL", "https://api.stripe.com")
        ).rstrip("/")
        self.timeout = float(getattr(settings, "STRIPE_TIMEOUT_SECONDS", os.getenv("STRIPE_TIMEOUT_SECONDS", "15")) or 15)
        self.api_version = (getattr(settings, "STRIPE_API_VERSION", "") or os.getenv("STRIPE_API_VERSION", "")).strip()
        if not self.secret_key:
            raise CommerceProviderError(
                "STRIPE_SECRET_KEY is not configured.", retryable=False
            )

    def _request(
        self,
        method: str,
        path: str,
        *,
        data: dict | None = None,
        idempotency_key: str | None = None,
        stripe_account: str | None = None,
    ) -> dict:
        headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Accept": "application/json",
            "User-Agent": "marketlift-commerce/2.0",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if self.api_version:
            headers["Stripe-Version"] = self.api_version
        if stripe_account:
            headers["Stripe-Account"] = stripe_account

        rows = _form_rows(data or {})
        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout,
                headers=headers,
            ) as client:
                if method.upper() == "GET":
                    response = client.request(method, path, params=rows)
                else:
                    response = client.request(method, path, data=rows)
        except httpx.HTTPError as exc:
            raise CommerceProviderError(
                "Stripe is temporarily unavailable.", retryable=True
            ) from exc

        if response.status_code >= 400:
            try:
                body = response.json()
                error = body.get("error") or body
                detail = error.get("message") if isinstance(error, dict) else error
            except ValueError:
                detail = response.text[:500]
            retryable = response.status_code >= 500 or response.status_code in {
                408,
                409,
                429,
            }
            raise CommerceProviderError(
                f"Stripe request failed ({response.status_code}): {detail}",
                retryable=retryable,
                status_code=response.status_code,
            )
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    def create_recipient(self, *, payload: dict, idempotency_key: str) -> dict:
        data = {
            "type": "express",
            "country": payload.get("country") or "BR",
            "email": payload.get("email"),
            "business_type": payload.get("business_type"),
            "capabilities": {"transfers": {"requested": True}},
            "business_profile": payload.get("business_profile") or {},
            "metadata": payload.get("metadata") or {},
        }
        result = self._request(
            "POST",
            "/v1/accounts",
            data=data,
            idempotency_key=idempotency_key,
        )
        disabled_reason = str(
            ((result.get("requirements") or {}).get("disabled_reason") or "")
        )
        if result.get("payouts_enabled"):
            result["status"] = "active"
        elif disabled_reason:
            result["status"] = "restricted"
        else:
            result["status"] = "pending"
        return result

    def create_kyc_link(self, recipient_id: str) -> dict:
        frontend_url = getattr(
            settings, "MARKETLIFT_FRONTEND_URL", "http://localhost:3001"
        ).rstrip("/")
        return self._request(
            "POST",
            "/v1/account_links",
            data={
                "account": recipient_id,
                "refresh_url": f"{frontend_url}/selling/payments?stripe=refresh",
                "return_url": f"{frontend_url}/selling/payments?stripe=return",
                "type": "account_onboarding",
            },
        )

    def create_customer(self, *, payload: dict, idempotency_key: str) -> dict:
        return self._request(
            "POST",
            "/v1/customers",
            data={
                "name": payload.get("name"),
                "email": payload.get("email"),
                "phone": payload.get("phone"),
                "metadata": payload.get("metadata") or {},
            },
            idempotency_key=idempotency_key,
        )

    def create_card(
        self, *, customer_id: str, token: str, idempotency_key: str
    ) -> dict:
        raise CommerceProviderError(
            "Direct card vaulting is disabled. Use Stripe-hosted Checkout.",
            retryable=False,
        )

    def create_order(self, *, payload: dict, idempotency_key: str) -> dict:
        method = str(payload.get("payment_method") or "").lower()
        if method not in {"card", "pix"}:
            raise CommerceProviderError(
                "Stripe Checkout supports only card or Pix for this flow.",
                retryable=False,
            )

        line_items = []
        for item in payload.get("items") or []:
            amount = int(item.get("amount") or item.get("unit_amount") or 0)
            quantity = int(item.get("quantity") or 1)
            name = str(
                item.get("description") or item.get("name") or "Marketlift item"
            )[:255]
            line_items.append(
                {
                    "price_data": {
                        "currency": str(payload.get("currency") or "BRL").lower(),
                        "unit_amount": amount,
                        "product_data": {"name": name},
                    },
                    "quantity": quantity,
                }
            )

        metadata = dict(payload.get("metadata") or {})
        data = {
            "mode": "payment",
            "success_url": payload.get("success_url"),
            "cancel_url": payload.get("cancel_url"),
            "client_reference_id": payload.get("code") or payload.get("reference"),
            "customer_email": payload.get("buyer_email"),
            "payment_method_types": [method],
            "line_items": line_items,
            "metadata": metadata,
            "payment_intent_data": {
                "metadata": metadata,
                "transfer_group": payload.get("code") or payload.get("reference"),
            },
            "locale": "pt-BR",
        }
        result = self._request(
            "POST",
            "/v1/checkout/sessions",
            data=data,
            idempotency_key=idempotency_key,
        )
        result["checkout_url"] = result.get("url") or ""
        return result

    def get_recipient_balance(self, recipient_id: str) -> dict:
        result = self._request(
            "GET",
            "/v1/balance",
            stripe_account=recipient_id,
        )
        amount = sum(
            int(row.get("amount") or 0)
            for row in (result.get("available") or [])
            if str(row.get("currency") or "").lower() == "brl"
        )
        return {"available_amount": amount, "raw": result}

    def create_transfer(
        self, *, recipient_id: str, amount_cents: int, idempotency_key: str
    ) -> dict:
        result = self._request(
            "POST",
            "/v1/transfers",
            data={
                "amount": amount_cents,
                "currency": "brl",
                "destination": recipient_id,
                "metadata": {"marketlift_payout_key": idempotency_key},
            },
            idempotency_key=idempotency_key,
        )
        # Stripe Transfers are created synchronously. Delivery to the connected
        # account balance is complete once the API returns the Transfer object.
        result.setdefault("status", "succeeded")
        return result

    def cancel_charge(
        self, charge_id: str, *, amount_cents: int | None = None
    ) -> dict:
        data = {"charge": charge_id}
        if amount_cents is not None:
            data["amount"] = amount_cents
        return self._request("POST", "/v1/refunds", data=data)
