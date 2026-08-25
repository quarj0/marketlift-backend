from django.conf import settings


def _active_profile():
    try:
        from .service import active_market_profile

        return active_market_profile()
    except Exception:
        return getattr(settings, "MARKETLIFT_MARKET", None)


def default_market_country_code() -> str:
    profile = _active_profile()
    return getattr(profile, "country_code", None) or getattr(
        settings, "MARKETLIFT_MARKET_COUNTRY_CODE", "BR"
    )


def default_market_currency() -> str:
    profile = _active_profile()
    return getattr(profile, "currency", None) or getattr(
        settings, "MARKETLIFT_MARKET_CURRENCY", "BRL"
    )


def default_market_locale() -> str:
    profile = _active_profile()
    return getattr(profile, "locale", None) or getattr(
        settings, "MARKETLIFT_MARKET_LOCALE", "pt-BR"
    )


def default_pricing_label() -> str:
    profile = _active_profile()
    symbol = getattr(profile, "currency_symbol", None) or getattr(
        settings, "MARKETLIFT_MARKET_CURRENCY_SYMBOL", "R$"
    )
    return f"Price ({symbol})"
