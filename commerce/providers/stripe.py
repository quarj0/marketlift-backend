from __future__ import annotations

import os

import stripe
from django.conf import settings
from stripe import StripeClient

from .base import CommerceProvider, CommerceProviderError


def _stripe_object_to_dict(value) -> dict:
    """Return a plain dict for either StripeObject or already-decoded test data."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    try:
        return dict(value)
    except (TypeError, ValueError) as exc:
        raise CommerceProviderError(
            "Stripe returned an unexpected response shape.",
            retryable=False,
        ) from exc


class StripeCommerceProvider(CommerceProvider):
    """Stripe Connect adapter for Marketlift marketplace commerce.

    Every Stripe API request goes through one StripeClient instance. The SDK pins
    the matching Stripe API version automatically, so Marketlift deliberately
    does not set Stripe-Version itself.

    Connected sellers use Accounts v2 with the recipient configuration because
    Marketlift is the merchant of record for the buyer charge. Buyer payments are
    created on the platform, then the seller share is transferred only after the
    Marketlift delivery/buyer-protection workflow releases the settlement.
    """

    code = "stripe"

    def __init__(self):
        self.secret_key = (
            getattr(settings, "STRIPE_SECRET_KEY", "")
            or os.getenv("STRIPE_SECRET_KEY", "")
        ).strip()
        if not self.secret_key:
            # PLACEHOLDER: set STRIPE_SECRET_KEY=sk_test_... (or sk_live_...)
            # in the backend environment. Never expose a secret key through a
            # NEXT_PUBLIC_* variable or commit it to Git.
            raise CommerceProviderError(
                "STRIPE_SECRET_KEY is not configured. Add the Stripe secret key "
                "to the backend environment before enabling commerce.",
                retryable=False,
            )

        # The latest installed Stripe SDK chooses its pinned API version
        # automatically. Network retries are safe because all write operations
        # below use an idempotency key where Stripe supports one.
        self.stripe_client = StripeClient(
            self.secret_key,
            max_network_retries=2,
        )

    def _call(self, operation, *args, **kwargs) -> dict:
        """Execute a Stripe SDK call and normalize provider errors."""
        try:
            return _stripe_object_to_dict(operation(*args, **kwargs))
        except stripe.StripeError as exc:
            status_code = getattr(exc, "http_status", None)
            retryable = (
                status_code is None
                or status_code >= 500
                or status_code in {408, 409, 429}
            )
            message = (
                getattr(exc, "user_message", None)
                or getattr(exc, "message", None)
                or str(exc)
            )
            raise CommerceProviderError(
                f"Stripe request failed: {message}",
                retryable=retryable,
                status_code=status_code,
            ) from exc

    def create_recipient(self, *, payload: dict, idempotency_key: str) -> dict:
        """Create the seller's Accounts v2 recipient account.

        Only the V2 properties required for this Marketlift account model are
        sent. In particular, there is no legacy top-level Account `type`.
        `dashboard="express"` gives the seller a Stripe-hosted management
        experience, while Marketlift remains responsible for pricing, Stripe
        fees, and losses for this platform-controlled flow.
        """
        display_name = str(
            payload.get("display_name")
            or payload.get("name")
            or payload.get("email")
            or "Marketlift seller"
        ).strip()
        contact_email = str(payload.get("email") or "").strip()
        country = str(payload.get("country") or "BR").strip().lower()

        if not contact_email:
            raise CommerceProviderError(
                "A seller email is required before Stripe Connect onboarding.",
                retryable=False,
            )

        params = {
            "display_name": display_name,
            "contact_email": contact_email,
            "identity": {
                "country": country,
            },
            "dashboard": "express",
            "defaults": {
                "responsibilities": {
                    "fees_collector": "application",
                    "losses_collector": "application",
                },
            },
            "configuration": {
                "recipient": {
                    "capabilities": {
                        "stripe_balance": {
                            "stripe_transfers": {
                                "requested": True,
                            },
                        },
                    },
                },
            },
        }
        return self._call(
            self.stripe_client.v2.core.accounts.create,
            params,
            {"idempotency_key": idempotency_key},
        )

    def get_recipient(self, recipient_id: str) -> dict:
        """Fetch live onboarding/capability status directly from Stripe."""
        return self._call(
            self.stripe_client.v2.core.accounts.retrieve,
            recipient_id,
            {
                "include": [
                    "configuration.recipient",
                    "requirements",
                ],
            },
        )

    def create_kyc_link(self, recipient_id: str) -> dict:
        """Create a single-use Stripe-hosted Account Link for onboarding."""
        frontend_url = getattr(
            settings,
            "MARKETLIFT_FRONTEND_URL",
            "http://localhost:3001",
        ).rstrip("/")
        return self._call(
            self.stripe_client.v2.core.account_links.create,
            {
                "account": recipient_id,
                "use_case": {
                    "type": "account_onboarding",
                    "account_onboarding": {
                        "configurations": ["recipient"],
                        "refresh_url": (
                            f"{frontend_url}/selling/payments?stripe=refresh"
                        ),
                        "return_url": (
                            f"{frontend_url}/selling/payments"
                            f"?stripe=return&accountId={recipient_id}"
                        ),
                    },
                },
            },
        )

    def create_customer(self, *, payload: dict, idempotency_key: str) -> dict:
        """Compatibility helper for provider-neutral code paths.

        Current Marketlift hosted Checkout uses customer_email and does not need
        to persist a Stripe Customer for each buyer.
        """
        return self._call(
            self.stripe_client.v1.customers.create,
            {
                "name": payload.get("name"),
                "email": payload.get("email"),
                "phone": payload.get("phone"),
                "metadata": payload.get("metadata") or {},
            },
            {"idempotency_key": idempotency_key},
        )

    def create_card(
        self,
        *,
        customer_id: str,
        token: str,
        idempotency_key: str,
    ) -> dict:
        raise CommerceProviderError(
            "Direct card vaulting is disabled. Marketlift uses Stripe-hosted Checkout "
            "so raw card data never reaches the Marketlift backend.",
            retryable=False,
        )

    def create_order(self, *, payload: dict, idempotency_key: str) -> dict:
        """Create hosted Checkout on the Marketlift platform account.

        This intentionally does NOT set payment_intent_data.transfer_data.
        A Destination Charge would move the seller share immediately, which
        conflicts with Marketlift buyer protection. Instead the full buyer charge
        lands on the platform and a later /v1/transfers call releases only the
        seller proceeds after delivery and the protection window.
        """
        method = str(payload.get("payment_method") or "").lower()
        if method not in {"card", "pix"}:
            raise CommerceProviderError(
                "Stripe Checkout supports only card or Pix for this flow.",
                retryable=False,
            )

        currency = str(payload.get("currency") or "BRL").lower()
        line_items = []
        for item in payload.get("items") or []:
            amount = int(item.get("amount") or item.get("unit_amount") or 0)
            quantity = int(item.get("quantity") or 1)
            name = str(
                item.get("description")
                or item.get("name")
                or "Marketlift item"
            )[:255]
            if amount <= 0 or quantity <= 0:
                raise CommerceProviderError(
                    "Stripe Checkout line items require a positive amount and quantity.",
                    retryable=False,
                )
            line_items.append(
                {
                    "price_data": {
                        "currency": currency,
                        "unit_amount": amount,
                        "product_data": {
                            "name": name,
                        },
                    },
                    "quantity": quantity,
                }
            )

        if not line_items:
            raise CommerceProviderError(
                "Stripe Checkout requires at least one line item.",
                retryable=False,
            )

        metadata = {
            str(key): str(value)
            for key, value in (payload.get("metadata") or {}).items()
            if value is not None
        }
        transfer_group = str(
            payload.get("code")
            or payload.get("reference")
            or metadata.get("marketlift_reference")
            or ""
        )

        params = {
            "mode": "payment",
            "success_url": payload.get("success_url"),
            "cancel_url": payload.get("cancel_url"),
            "client_reference_id": (
                payload.get("code") or payload.get("reference")
            ),
            "customer_email": payload.get("buyer_email"),
            "payment_method_types": [method],
            "line_items": line_items,
            "metadata": metadata,
            "payment_intent_data": {
                "metadata": metadata,
                "transfer_group": transfer_group,
            },
            "locale": "pt-BR",
        }
        if payload.get("expires_at"):
            params["expires_at"] = int(payload["expires_at"])

        result = self._call(
            self.stripe_client.v1.checkout.sessions.create,
            params,
            {"idempotency_key": idempotency_key},
        )
        result["checkout_url"] = result.get("url") or ""
        return result

    def get_recipient_balance(self, recipient_id: str) -> dict:
        """Read a connected account balance through the same StripeClient."""
        result = self._call(
            self.stripe_client.v1.balance.retrieve,
            None,
            {"stripe_account": recipient_id},
        )
        available_amount = sum(
            int(row.get("amount") or 0)
            for row in (result.get("available") or [])
            if str(row.get("currency") or "").lower() == "brl"
        )
        return {
            "available_amount": available_amount,
            "raw": result,
        }

    def create_transfer(
        self,
        *,
        recipient_id: str,
        amount_cents: int,
        idempotency_key: str,
    ) -> dict:
        """Release seller proceeds after Marketlift marks them available."""
        if amount_cents <= 0:
            raise CommerceProviderError(
                "Stripe transfer amount must be positive.",
                retryable=False,
            )
        result = self._call(
            self.stripe_client.v1.transfers.create,
            {
                "amount": amount_cents,
                "currency": "brl",
                "destination": recipient_id,
                "metadata": {
                    "marketlift_payout_key": idempotency_key,
                },
            },
            {"idempotency_key": idempotency_key},
        )
        # Stripe Transfers are synchronous objects. The connected account balance
        # receives the transfer when this call succeeds.
        result.setdefault("status", "succeeded")
        return result

    def cancel_charge(
        self,
        charge_id: str,
        *,
        amount_cents: int | None = None,
    ) -> dict:
        params = {"charge": charge_id}
        if amount_cents is not None:
            params["amount"] = amount_cents
        return self._call(
            self.stripe_client.v1.refunds.create,
            params,
        )
