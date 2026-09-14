"""Marketplace commerce domain configuration.

The main settings module remains provider-neutral. Commerce-specific settings are
loaded here from environment variables when this domain is registered by GraphQL,
Celery, or the webhook view.
"""

import os

from django.conf import settings


def _set_default(name: str, value):
    if not hasattr(settings, name):
        setattr(settings, name, value)


_set_default("MARKETLIFT_COMMERCE_PROVIDER", os.getenv("MARKETLIFT_COMMERCE_PROVIDER", "pagarme").strip())
_set_default("PAGARME_SECRET_KEY", os.getenv("PAGARME_SECRET_KEY", "").strip())
_set_default("PAGARME_BASE_URL", os.getenv("PAGARME_BASE_URL", "https://api.pagar.me/core/v5").strip())
_set_default("PAGARME_MARKETPLACE_RECIPIENT_ID", os.getenv("PAGARME_MARKETPLACE_RECIPIENT_ID", "").strip())
_set_default("PAGARME_WEBHOOK_TOKEN", os.getenv("PAGARME_WEBHOOK_TOKEN", "").strip())
_set_default("PAGARME_TIMEOUT_SECONDS", float(os.getenv("PAGARME_TIMEOUT_SECONDS", "15")))
_set_default("PAGARME_PIX_EXPIRES_SECONDS", int(os.getenv("PAGARME_PIX_EXPIRES_SECONDS", "1800")))
_set_default("PAGARME_STATEMENT_DESCRIPTOR", os.getenv("PAGARME_STATEMENT_DESCRIPTOR", "MARKETLIFT").strip())
_set_default("MARKETLIFT_COMMERCE_FEE_BPS", int(os.getenv("MARKETLIFT_COMMERCE_FEE_BPS", "500")))
_set_default("MARKETLIFT_BUYER_PROTECTION_HOURS", int(os.getenv("MARKETLIFT_BUYER_PROTECTION_HOURS", "48")))
_set_default("MARKETLIFT_LOCAL_DELIVERY_FEE_CENTS", int(os.getenv("MARKETLIFT_LOCAL_DELIVERY_FEE_CENTS", "0")))

if hasattr(settings, "CELERY_BEAT_SCHEDULE"):
    settings.CELERY_BEAT_SCHEDULE.setdefault(
        "release-due-commerce-settlements",
        {
            "task": "payments.tasks.release_due_commerce_settlements",
            "schedule": 300.0,
        },
    )
