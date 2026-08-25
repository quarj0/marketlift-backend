from __future__ import annotations

from django.conf import settings
from django.db import OperationalError, ProgrammingError, transaction

from marketlift.markets.profiles import list_market_profiles


def _bootstrap_code() -> str:
    profile = getattr(settings, "MARKETLIFT_MARKET", None)
    code = getattr(profile, "country_code", None) or getattr(
        settings, "MARKETLIFT_MARKET_COUNTRY_CODE", "BR"
    )
    supported = {profile.country_code for profile in list_market_profiles()}
    code = str(code or "BR").strip().upper()
    return code if code in supported else "BR"


def _defaults_for_profile(profile, *, sort_order: int) -> dict:
    return {
        "country_name": profile.country_name,
        "locale": profile.locale,
        "django_language_code": profile.django_language_code,
        "currency": profile.currency,
        "currency_symbol": profile.currency_symbol,
        "timezone": profile.timezone,
        "geocoder_language": profile.geocoder_language,
        "payment_provider": profile.default_payment_provider,
        "payment_methods": list(profile.payment_methods),
        "identity_provider": "disabled",
        "identity_label": profile.identity_label,
        "identity_key": profile.identity_key,
        "currency_aliases": list(profile.currency_aliases),
        "currency_subunit_factor": profile.currency_subunit_factor,
        "hierarchical_location_catalog": profile.hierarchical_location_catalog,
        "sort_order": sort_order,
    }


def ensure_market_catalog(*, using: str = "default") -> int:
    """Ensure supported market reference rows exist without overwriting admin choices.

    ``Market`` rows are reference/configuration data, not disposable test data. A
    reused Django test database can be flushed by ``TransactionTestCase`` while
    its migration history remains intact; in that situation the original data
    migration will not run again. This helper safely restores only *missing*
    catalog rows and guarantees an enabled default if every row was lost.

    Existing rows are never updated here, so admin enable/disable/default,
    provider, and payment-method changes remain authoritative.
    """

    from platform_settings.models import Market

    profiles = list_market_profiles()
    bootstrap = _bootstrap_code()
    created = 0
    try:
        with transaction.atomic(using=using):
            manager = Market.objects.using(using)
            for index, profile in enumerate(profiles):
                _, was_created = manager.get_or_create(
                    code=profile.country_code,
                    defaults={
                        **_defaults_for_profile(profile, sort_order=index),
                        "is_enabled": profile.country_code == bootstrap,
                        "is_default": profile.country_code == bootstrap,
                    },
                )
                created += int(was_created)

            enabled = manager.filter(is_enabled=True)
            if not enabled.exists():
                fallback = manager.filter(code=bootstrap).first() or manager.order_by(
                    "sort_order", "country_name"
                ).first()
                if fallback is not None:
                    manager.filter(pk=fallback.pk).update(is_enabled=True, is_default=True)
            elif not enabled.filter(is_default=True).exists():
                fallback = enabled.filter(code=bootstrap).first() or enabled.order_by(
                    "sort_order", "country_name"
                ).first()
                if fallback is not None:
                    manager.filter(is_default=True).update(is_default=False)
                    manager.filter(pk=fallback.pk).update(is_default=True)
    except (OperationalError, ProgrammingError):
        # Expected before the Market migration exists (startup/migration bootstrap).
        return 0

    try:
        from marketlift.markets.service import invalidate_market_cache

        invalidate_market_cache()
    except Exception:
        pass
    return created
