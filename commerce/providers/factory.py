from django.conf import settings

from .pagarme import PagarMeCommerceProvider
from .stripe import StripeCommerceProvider


def get_commerce_provider():
    provider = getattr(settings, "MARKETLIFT_COMMERCE_PROVIDER", "stripe").strip().lower()
    if provider == "stripe":
        return StripeCommerceProvider()
    if provider == "pagarme":
        return PagarMeCommerceProvider()
    raise RuntimeError(f"Unsupported commerce provider: {provider}")
