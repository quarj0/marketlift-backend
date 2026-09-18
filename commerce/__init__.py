"""Marketplace commerce domain configuration.

Stripe Connect is the sole marketplace-commerce provider. Provider secrets stay
backend-only and are loaded from environment variables when this domain is
registered by GraphQL, Celery, or webhook views.
"""

import os

from django.conf import settings


def _set_default(name: str, value):
    if not hasattr(settings, name):
        setattr(settings, name, value)


_set_default(
    "MARKETLIFT_COMMERCE_PROVIDER",
    os.getenv("MARKETLIFT_COMMERCE_PROVIDER", "stripe").strip().lower(),
)
_set_default("STRIPE_SECRET_KEY", os.getenv("STRIPE_SECRET_KEY", "").strip())
_set_default(
    "STRIPE_WEBHOOK_SECRET",
    os.getenv("STRIPE_WEBHOOK_SECRET", "").strip(),
)
_set_default(
    "STRIPE_CONNECT_WEBHOOK_SECRET",
    os.getenv("STRIPE_CONNECT_WEBHOOK_SECRET", "").strip(),
)
_set_default(
    "STRIPE_WEBHOOK_TOLERANCE_SECONDS",
    int(os.getenv("STRIPE_WEBHOOK_TOLERANCE_SECONDS", "300")),
)
_set_default(
    "MARKETLIFT_COMMERCE_FEE_BPS",
    int(os.getenv("MARKETLIFT_COMMERCE_FEE_BPS", "500")),
)
_set_default(
    "MARKETLIFT_BUYER_PROTECTION_HOURS",
    int(os.getenv("MARKETLIFT_BUYER_PROTECTION_HOURS", "48")),
)
_set_default(
    "MARKETLIFT_LOCAL_DELIVERY_FEE_CENTS",
    int(os.getenv("MARKETLIFT_LOCAL_DELIVERY_FEE_CENTS", "0")),
)

if hasattr(settings, "CELERY_BEAT_SCHEDULE"):
    settings.CELERY_BEAT_SCHEDULE.setdefault(
        "release-due-commerce-settlements",
        {
            "task": "payments.tasks.release_due_commerce_settlements",
            "schedule": 300.0,
        },
    )

from . import services as _services  # noqa: E402
from . import review_fixes as _review_fixes  # noqa: E402
from . import checkout_reliability as _checkout_reliability  # noqa: E402
from . import stripe_runtime as _stripe_runtime  # noqa: E402

# Keep shared fulfillment/refund hardening while making every seller-onboarding,
# checkout and payout entry point resolve to Stripe Connect.
_services.activate_seller_payments = _stripe_runtime.activate_seller_payments
_services.create_checkout_order = _stripe_runtime.create_checkout_order
_services.withdraw_available_balance = _stripe_runtime.withdraw_available_balance
_services.open_order_dispute = _review_fixes.open_order_dispute
_services.seller_wallet = _review_fixes.seller_wallet
_services.finalize_order_refund = _review_fixes.finalize_order_refund
_services.refund_order = _review_fixes.refund_order
