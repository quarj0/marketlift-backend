from __future__ import annotations

import hashlib

from django.core.exceptions import ValidationError

from .providers import get_commerce_provider
from .providers.base import CommerceProviderError
from .services import _buyer_customer_payload


def vault_card_token(*, buyer, card_token: str, customer_document: str, customer_phone: str) -> str:
    """Exchange a short-lived browser token for a provider card id.

    Raw PAN/CVV values never enter Marketlift. The browser sends those directly to
    Pagar.me's token endpoint and only the resulting short-lived token reaches this
    service.
    """
    token = (card_token or "").strip()
    if not token:
        raise ValidationError({"cardToken": "A Pagar.me card token is required."})

    customer = _buyer_customer_payload(
        buyer=buyer,
        document=customer_document,
        phone=customer_phone,
    )
    provider = get_commerce_provider()
    document = str(customer["document"])
    customer_key = hashlib.sha256(
        f"{buyer.id}:{document}".encode("utf-8")
    ).hexdigest()[:32]
    customer_result = provider.create_customer(
        payload=customer,
        idempotency_key=f"commerce-customer:{customer_key}",
    )
    customer_id = str(customer_result.get("id") or "").strip()
    if not customer_id:
        raise CommerceProviderError("Pagar.me did not return a customer id.")

    token_key = hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]
    card_result = provider.create_card(
        customer_id=customer_id,
        token=token,
        idempotency_key=f"commerce-card:{buyer.id}:{token_key}",
    )
    card_id = str(card_result.get("id") or "").strip()
    if not card_id:
        raise CommerceProviderError("Pagar.me did not return a card id.")
    return card_id
