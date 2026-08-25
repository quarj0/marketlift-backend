from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import OperationalError, ProgrammingError
try:
    from django.test.testcases import DatabaseOperationForbidden
except Exception:  # pragma: no cover
    DatabaseOperationForbidden = AssertionError

from .profiles import MarketProfile, get_market_profile


def invalidate_market_cache() -> None:
    try:
        cache.delete("ml:markets:catalog:v1")
    except Exception:
        pass


def _db_market_rows(*, enabled_only: bool = False):
    """Return lightweight market rows when the admin-backed table is available.

    The six-row catalog is cached briefly to avoid a database query on every
    search/payment request. Admin updates invalidate the cache on transaction
    commit. Startup/migration paths fall back to bootstrap settings if the table
    does not exist yet.
    """

    rows = None
    try:
        rows = cache.get("ml:markets:catalog:v1")
    except Exception:
        rows = None
    if rows is None:
        try:
            from platform_settings.models import Market

            fields = (
                "code",
                "country_name",
                "locale",
                "django_language_code",
                "currency",
                "currency_symbol",
                "timezone",
                "geocoder_language",
                "payment_provider",
                "payment_methods",
                "identity_provider",
                "identity_label",
                "identity_key",
                "currency_aliases",
                "currency_subunit_factor",
                "hierarchical_location_catalog",
                "is_enabled",
                "is_default",
                "sort_order",
            )
            rows = list(
                Market.objects.order_by("sort_order", "country_name").values(*fields)
            )
            from .profiles import list_market_profiles

            expected_codes = {profile.country_code for profile in list_market_profiles()}
            present_codes = {row["code"] for row in rows}
            if not expected_codes.issubset(present_codes):
                # A reused test database may have been flushed while migration
                # history was preserved, or a reference row may have been
                # removed directly. Restore only missing catalog rows rather
                # than surfacing raw DoesNotExist errors.
                from platform_settings.market_catalog import ensure_market_catalog

                ensure_market_catalog()
                rows = list(
                    Market.objects.order_by("sort_order", "country_name").values(*fields)
                )
            try:
                cache.set("ml:markets:catalog:v1", rows, timeout=60)
            except Exception:
                pass
        except (OperationalError, ProgrammingError, DatabaseOperationForbidden):
            return []
    objects = [SimpleNamespace(**row) for row in rows]
    if enabled_only:
        objects = [row for row in objects if row.is_enabled]
    return objects


def _row_to_profile(row) -> MarketProfile:
    base = get_market_profile(row.code)
    return replace(
        base,
        country_name=row.country_name,
        locale=row.locale,
        django_language_code=row.django_language_code,
        currency=row.currency,
        currency_symbol=row.currency_symbol,
        timezone=row.timezone,
        geocoder_language=row.geocoder_language,
        default_payment_provider=row.payment_provider,
        payment_methods=tuple(row.payment_methods or ()),
        identity_label=row.identity_label,
        identity_key=row.identity_key,
        currency_aliases=tuple(row.currency_aliases or ()),
        currency_subunit_factor=row.currency_subunit_factor,
        hierarchical_location_catalog=row.hierarchical_location_catalog,
    )


def active_market_profile() -> MarketProfile:
    rows = _db_market_rows(enabled_only=True)
    if rows:
        default = next((row for row in rows if row.is_default), rows[0])
        return _row_to_profile(default)
    return settings.MARKETLIFT_MARKET


def enabled_market_profiles() -> tuple[MarketProfile, ...]:
    rows = _db_market_rows(enabled_only=True)
    if rows:
        return tuple(_row_to_profile(row) for row in rows)
    return tuple(settings.MARKETLIFT_ENABLED_MARKETS)


def profile_for_country_code(country_code: str | None) -> MarketProfile:
    code = (country_code or active_market_profile().country_code).strip().upper()
    rows = _db_market_rows(enabled_only=False)
    if rows:
        for row in rows:
            if row.code == code:
                if not row.is_enabled:
                    raise ValidationError(
                        {"country_code": f"Country {code!r} is not enabled."}
                    )
                return _row_to_profile(row)
        raise ValidationError({"country_code": f"Country {code!r} is not configured."})

    for profile in enabled_market_profiles():
        if profile.country_code == code:
            return profile
    supported = ", ".join(p.country_code for p in enabled_market_profiles())
    raise ValidationError(
        {"country_code": f"Country {code!r} is not enabled. Supported: {supported}."}
    )


def normalize_enabled_country_code(country_code: str | None) -> str:
    return profile_for_country_code(country_code).country_code


def default_country_code() -> str:
    return active_market_profile().country_code


def identity_provider_for_country_code(country_code: str | None) -> str:
    code = profile_for_country_code(country_code).country_code
    rows = _db_market_rows(enabled_only=False)
    for row in rows:
        if row.code == code:
            return (row.identity_provider or "disabled").strip().lower()
    return str(
        getattr(settings, "MARKETLIFT_IDENTITY_VERIFICATION_PROVIDER", "disabled")
    ).strip().lower()
