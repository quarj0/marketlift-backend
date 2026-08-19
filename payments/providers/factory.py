from django.conf import settings
from .base import PaymentProviderError
from .mock import MockPaymentProvider
from .mercado_pago import MercadoPagoProvider


def get_payment_provider():
    name = getattr(settings, "MARKETLIFT_PAYMENT_PROVIDER", "mock").strip().lower()
    if name == "mock":
        return MockPaymentProvider()
    if name in {"mercado_pago", "mercadopago"}:
        return MercadoPagoProvider()
    raise PaymentProviderError(f"Unknown payment provider: {name}")
