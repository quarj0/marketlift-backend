from django.conf import settings

from .pagarme import PagarMeCommerceProvider


def get_commerce_provider():
    provider = getattr(settings, "MARKETLIFT_COMMERCE_PROVIDER", "pagarme")
    if provider != "pagarme":
        raise RuntimeError(f"Unsupported commerce provider: {provider}")
    return PagarMeCommerceProvider()
