from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

from marketlift.markets.defaults import (
    default_market_country_code,
    default_market_currency,
    default_market_locale,
    default_pricing_label,
)
from marketlift.markets.profiles import get_market_profile
from marketlift.markets.service import invalidate_market_cache, profile_for_country_code

GH = get_market_profile("GH")
BR = get_market_profile("BR")


class MarketProfileTests(SimpleTestCase):
    def setUp(self):
        # These tests intentionally exercise the settings/bootstrap fallback
        # without database access. Do not reuse DB-backed market rows cached by
        # earlier TestCase classes in the same test process.
        invalidate_market_cache()

    def tearDown(self):
        invalidate_market_cache()

    def test_market_dial_codes_are_public_configuration(self):
        self.assertEqual(BR.dial_code, "+55")
        self.assertEqual(GH.dial_code, "+233")
        self.assertEqual(BR.as_public_dict()["dialCode"], "+55")
        self.assertEqual(GH.as_public_dict()["dialCode"], "+233")

    def test_ghana_profile(self):
        self.assertEqual(GH.currency, "GHS")
        self.assertEqual(GH.currency_symbol, "GH₵")
        self.assertEqual(GH.default_payment_provider, "paystack")
        self.assertEqual(GH.payment_methods, ("card", "mobile_money"))
        self.assertEqual(GH.identity_label, "Ghana Card")

    @override_settings(
        MARKETLIFT_MARKET=GH,
        MARKETLIFT_MARKET_COUNTRY_CODE="GH",
        MARKETLIFT_MARKET_CURRENCY="GHS",
        MARKETLIFT_MARKET_CURRENCY_SYMBOL="GH₵",
        MARKETLIFT_MARKET_LOCALE="en-GH",
    )
    def test_model_defaults_follow_active_market(self):
        self.assertEqual(default_market_country_code(), "GH")
        self.assertEqual(default_market_currency(), "GHS")
        self.assertEqual(default_market_locale(), "en-GH")
        self.assertEqual(default_pricing_label(), "Price (GH₵)")

    @override_settings(
        MARKETLIFT_MARKET=GH,
        MARKETLIFT_MARKET_CODE="GH",
        MARKETLIFT_MARKET_COUNTRY_CODE="GH",
        MARKETLIFT_ENABLED_MARKETS=(GH,),
        MARKETLIFT_SUPPORTED_COUNTRY_CODES=("GH",),
    )
    def test_disabled_country_is_rejected(self):
        self.assertEqual(profile_for_country_code("GH"), GH)
        with self.assertRaises(ValidationError):
            profile_for_country_code("BR")
