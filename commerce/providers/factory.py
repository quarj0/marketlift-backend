from django.conf import settings

from .stripe import StripeCommerceProvider


def get_commerce_provider():
    provider = getattr(settings, "MARKETLIFT_COMMERCE_PROVIDER", "stripe").strip().lower()
    if provider != "stripe":
        raise RuntimeError(
            f"Unsupported commerce provider: {provider}. "
            "Marketlift marketplace commerce uses Stripe Connect."
        )
    return StripeCommerceProvider()
