from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketProfile:
    code: str
    country_code: str
    country_name: str
    locale: str
    django_language_code: str
    currency: str
    currency_symbol: str
    timezone: str
    geocoder_language: str
    default_payment_provider: str
    payment_methods: tuple[str, ...]
    identity_label: str
    identity_key: str
    currency_aliases: tuple[str, ...] = ()
    currency_subunit_factor: int = 100
    hierarchical_location_catalog: bool = False

    def as_public_dict(self) -> dict:
        return {
            "code": self.code,
            "countryCode": self.country_code,
            "countryName": self.country_name,
            "locale": self.locale,
            "languageCode": self.django_language_code,
            "currency": self.currency,
            "currencySymbol": self.currency_symbol,
            "paymentProvider": self.default_payment_provider,
            "paymentMethods": list(self.payment_methods),
            "identityLabel": self.identity_label,
            "identityKey": self.identity_key,
            "locationMode": (
                "catalog" if self.hierarchical_location_catalog else "geocoder"
            ),
        }


# Payment method values intentionally match payments.models.Payment.Method values.
# These profiles are configuration, not business logic; a new country can be added
# without changing listing/search/payment domain services.
_MARKETS: dict[str, MarketProfile] = {
    "BR": MarketProfile(
        code="BR",
        country_code="BR",
        country_name="Brazil",
        locale="pt-BR",
        django_language_code="pt-br",
        currency="BRL",
        currency_symbol="R$",
        timezone="America/Sao_Paulo",
        geocoder_language="pt-BR,en",
        default_payment_provider="mercado_pago",
        payment_methods=("pix", "card", "boleto"),
        identity_label="CPF",
        identity_key="cpf",
        currency_aliases=("r$", "brl", "real", "reais"),
        hierarchical_location_catalog=True,
    ),
    "GH": MarketProfile(
        code="GH",
        country_code="GH",
        country_name="Ghana",
        locale="en-GH",
        django_language_code="en-gb",
        currency="GHS",
        currency_symbol="GH₵",
        timezone="Africa/Accra",
        geocoder_language="en-GH,en",
        default_payment_provider="paystack",
        payment_methods=("card", "mobile_money"),
        identity_label="Ghana Card",
        identity_key="national_id",
        currency_aliases=("gh₵", "ghs", "cedi", "cedis", "₵"),
    ),
    "NG": MarketProfile(
        code="NG",
        country_code="NG",
        country_name="Nigeria",
        locale="en-NG",
        django_language_code="en-gb",
        currency="NGN",
        currency_symbol="₦",
        timezone="Africa/Lagos",
        geocoder_language="en-NG,en",
        default_payment_provider="paystack",
        payment_methods=("card", "bank_transfer", "ussd"),
        identity_label="National Identity Number (NIN)",
        identity_key="national_id",
        currency_aliases=("₦", "ngn", "naira"),
    ),
    "KE": MarketProfile(
        code="KE",
        country_code="KE",
        country_name="Kenya",
        locale="en-KE",
        django_language_code="en-gb",
        currency="KES",
        currency_symbol="KSh",
        timezone="Africa/Nairobi",
        geocoder_language="en-KE,sw,en",
        default_payment_provider="paystack",
        payment_methods=("card", "mobile_money"),
        identity_label="National ID",
        identity_key="national_id",
        currency_aliases=("ksh", "kes", "shilling", "shillings"),
    ),
    "ZA": MarketProfile(
        code="ZA",
        country_code="ZA",
        country_name="South Africa",
        locale="en-ZA",
        django_language_code="en-gb",
        currency="ZAR",
        currency_symbol="R",
        timezone="Africa/Johannesburg",
        geocoder_language="en-ZA,en",
        default_payment_provider="paystack",
        payment_methods=("card", "eft"),
        identity_label="South African ID",
        identity_key="national_id",
        currency_aliases=("zar", "rand"),
    ),
    "CI": MarketProfile(
        code="CI",
        country_code="CI",
        country_name="Côte d’Ivoire",
        locale="fr-CI",
        django_language_code="fr",
        currency="XOF",
        currency_symbol="FCFA",
        timezone="Africa/Abidjan",
        geocoder_language="fr-CI,fr,en",
        default_payment_provider="paystack",
        payment_methods=("card", "mobile_money"),
        identity_label="National ID",
        identity_key="national_id",
        currency_aliases=("xof", "fcfa", "cfa"),
        currency_subunit_factor=100,
    ),
}


def get_market_profile(code: str | None) -> MarketProfile:
    normalized = (code or "BR").strip().upper()
    try:
        return _MARKETS[normalized]
    except KeyError as exc:
        supported = ", ".join(sorted(_MARKETS))
        raise ValueError(
            f"Unsupported MARKETLIFT_MARKET_CODE {normalized!r}. Supported: {supported}."
        ) from exc


def list_market_profiles() -> tuple[MarketProfile, ...]:
    return tuple(_MARKETS[key] for key in sorted(_MARKETS))


def market_profiles_for_codes(
    codes: list[str] | tuple[str, ...],
) -> tuple[MarketProfile, ...]:
    seen: set[str] = set()
    profiles: list[MarketProfile] = []
    for code in codes:
        profile = get_market_profile(code)
        if profile.code not in seen:
            profiles.append(profile)
            seen.add(profile.code)
    return tuple(profiles)
