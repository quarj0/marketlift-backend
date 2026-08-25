from django.conf import settings


def default_market_country_code() -> str:
    return getattr(settings, "MARKETLIFT_MARKET_COUNTRY_CODE", "BR")


def default_market_currency() -> str:
    return getattr(settings, "MARKETLIFT_MARKET_CURRENCY", "BRL")


def default_market_locale() -> str:
    return getattr(settings, "MARKETLIFT_MARKET_LOCALE", "pt-BR")


def default_pricing_label() -> str:
    symbol = getattr(settings, "MARKETLIFT_MARKET_CURRENCY_SYMBOL", "R$")
    return f"Price ({symbol})"
