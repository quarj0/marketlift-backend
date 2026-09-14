from __future__ import annotations

import httpx
from django.conf import settings

from .base import CommerceProvider, CommerceProviderError


class PagarMeCommerceProvider(CommerceProvider):
    code = "pagarme"

    def __init__(self):
        self.secret_key = getattr(settings, "PAGARME_SECRET_KEY", "").strip()
        self.base_url = getattr(
            settings, "PAGARME_BASE_URL", "https://api.pagar.me/core/v5"
        ).rstrip("/")
        self.timeout = float(getattr(settings, "PAGARME_TIMEOUT_SECONDS", 15))
        if not self.secret_key:
            raise CommerceProviderError("PAGARME_SECRET_KEY is not configured.")

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        headers = {
            "Accept": "application/json",
            "User-Agent": "marketlift-commerce/1.0",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            with httpx.Client(
                base_url=self.base_url,
                auth=httpx.BasicAuth(self.secret_key, ""),
                timeout=self.timeout,
                headers=headers,
            ) as client:
                response = client.request(method, path, json=json)
        except httpx.HTTPError as exc:
            raise CommerceProviderError("Pagar.me is temporarily unavailable.") from exc
        if response.status_code >= 400:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text[:500]
            raise CommerceProviderError(
                f"Pagar.me request failed ({response.status_code}): {detail}"
            )
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    def create_recipient(self, *, payload: dict, idempotency_key: str) -> dict:
        return self._request(
            "POST", "/recipients", json=payload, idempotency_key=idempotency_key
        )

    def create_kyc_link(self, recipient_id: str) -> dict:
        return self._request("POST", f"/recipients/{recipient_id}/kyc_link")

    def create_customer(self, *, payload: dict, idempotency_key: str) -> dict:
        return self._request(
            "POST", "/customers", json=payload, idempotency_key=idempotency_key
        )

    def create_card(
        self, *, customer_id: str, token: str, idempotency_key: str
    ) -> dict:
        return self._request(
            "POST",
            f"/customers/{customer_id}/cards",
            json={"token": token},
            idempotency_key=idempotency_key,
        )

    def create_order(self, *, payload: dict, idempotency_key: str) -> dict:
        return self._request(
            "POST", "/orders", json=payload, idempotency_key=idempotency_key
        )

    def get_recipient_balance(self, recipient_id: str) -> dict:
        return self._request("GET", f"/recipients/{recipient_id}/balance")

    def create_transfer(
        self, *, recipient_id: str, amount_cents: int, idempotency_key: str
    ) -> dict:
        return self._request(
            "POST",
            "/transfers",
            json={"amount": amount_cents, "recipient_id": recipient_id},
            idempotency_key=idempotency_key,
        )

    def cancel_charge(self, charge_id: str, *, amount_cents: int | None = None) -> dict:
        payload = {"amount": amount_cents} if amount_cents is not None else None
        return self._request("DELETE", f"/charges/{charge_id}", json=payload)
