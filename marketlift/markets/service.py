from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError

from .profiles import MarketProfile


def active_market_profile() -> MarketProfile:
    return settings.MARKETLIFT_MARKET


def enabled_market_profiles() -> tuple[MarketProfile, ...]:
    return tuple(settings.MARKETLIFT_ENABLED_MARKETS)


def profile_for_country_code(country_code: str | None) -> MarketProfile:
    code = (country_code or settings.MARKETLIFT_MARKET_COUNTRY_CODE).strip().upper()
    for profile in enabled_market_profiles():
        if profile.country_code == code:
            return profile
    supported = ", ".join(settings.MARKETLIFT_SUPPORTED_COUNTRY_CODES)
    raise ValidationError(
        {"country_code": f"Country {code!r} is not enabled. Supported: {supported}."}
    )


def normalize_enabled_country_code(country_code: str | None) -> str:
    return profile_for_country_code(country_code).country_code
