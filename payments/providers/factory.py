from __future__ import annotations

from django.conf import settings

from marketlift.markets.service import enabled_market_profiles, profile_for_country_code

from .base import PaymentProviderError
from .mercado_pago import MercadoPagoProvider
from .mock import MockPaymentProvider
from .paystack import PaystackProvider


def _configured_name(
    *, name: str | None = None, country_code: str | None = None
) -> str:
    if name is not None:
        return str(name).strip().lower()
    # Once markets are database-managed, provider selection is a market business
    # setting. The global environment value remains only a bootstrap/diagnostic
    # fallback for pre-migration or provider-direct operations.
    if country_code:
        return profile_for_country_code(country_code).default_payment_provider
    configured = (
        str(getattr(settings, "MARKETLIFT_PAYMENT_PROVIDER", "auto")).strip().lower()
    )
    if configured in {"auto", "market", "market_default"}:
        return profile_for_country_code(None).default_payment_provider
    return configured


def get_payment_provider(*, name: str | None = None, country_code: str | None = None):
    provider = _configured_name(name=name, country_code=country_code)
    if provider == "mock":
        return MockPaymentProvider()
    if provider in {"mercado_pago", "mercadopago"}:
        return MercadoPagoProvider()
    if provider == "paystack":
        return PaystackProvider()
    if provider in {"", "disabled", "none"}:
        raise PaymentProviderError("Payment provider is disabled.")
    raise PaymentProviderError(f"Unknown payment provider: {provider}")


def enabled_payment_provider_names() -> set[str]:
    return {
        profile.default_payment_provider
        for profile in enabled_market_profiles()
        if profile.default_payment_provider not in {"", "disabled", "none"}
    }


def payment_provider_enabled(name: str) -> bool:
    normalized = (name or "").strip().lower()
    if normalized == "mercadopago":
        normalized = "mercado_pago"
    return normalized in enabled_payment_provider_names()
