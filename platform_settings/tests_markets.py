from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User
from marketlift.markets.pricing import (
    market_pricing_readiness,
    promotion_price,
    seller_plan_price,
)
from marketlift.markets.service import (
    active_market_profile,
    invalidate_market_cache,
    profile_for_country_code,
)
from payments.services import create_subscription_payment
from platform_settings.market_catalog import ensure_market_catalog
from platform_settings.models import (
    Market,
    PromotionProductMarketPrice,
    SellerPlanMarketPrice,
)
from promotions.models import PromotionProduct
from sellers.models import SellerProfile
from subscriptions.models import SellerPlan


class MarketConfigurationTests(TestCase):
    def setUp(self):
        ensure_market_catalog()
        invalidate_market_cache()
        self.br = Market.objects.get(code="BR")
        self.gh = Market.objects.get(code="GH")

    def _enable_ghana(self, *, default=False, provider="mock"):
        self.gh.is_enabled = True
        self.gh.is_default = default
        self.gh.payment_provider = provider
        self.gh.payment_methods = ["card", "mobile_money"]
        self.gh.save()
        invalidate_market_cache()
        self.gh.refresh_from_db()

    def test_database_market_controls_runtime_enabled_countries(self):
        self._enable_ghana(default=False)
        self.assertEqual(profile_for_country_code("GH").currency, "GHS")
        self.br.is_default = False
        self.br.is_enabled = False
        self.br.save()
        invalidate_market_cache()
        with self.assertRaises(ValidationError):
            profile_for_country_code("BR")

    def test_switching_default_market_unsets_previous_default(self):
        self.br.is_enabled = True
        self.br.is_default = True
        self.br.save()
        self._enable_ghana(default=True)
        self.br.refresh_from_db()
        self.assertFalse(self.br.is_default)
        self.assertTrue(self.gh.is_default)
        self.assertEqual(active_market_profile().country_code, "GH")

    def test_repeated_default_switch_keeps_exactly_one_default(self):
        self.br.is_enabled = True
        self.br.save()
        self._enable_ghana()
        for index in range(50):
            row = self.br if index % 2 == 0 else self.gh
            row.refresh_from_db()
            row.is_enabled = True
            row.is_default = True
            row.save()
            self.assertEqual(Market.objects.filter(is_default=True).count(), 1)

    def test_disabled_market_cannot_be_default(self):
        self.gh.is_enabled = False
        self.gh.is_default = True
        with self.assertRaises(ValidationError):
            self.gh.full_clean()

    def test_public_market_endpoint_reads_database_state(self):
        self._enable_ghana(default=True)
        response = APIClient().get("/api/market/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["active"]["countryCode"], "GH")
        enabled = {row["countryCode"] for row in payload["enabledMarkets"]}
        self.assertIn("GH", enabled)

    def test_empty_catalog_is_restored_without_raw_does_not_exist(self):
        Market.objects.all().delete()
        invalidate_market_cache()
        profile = active_market_profile()
        self.assertTrue(Market.objects.filter(code=profile.country_code).exists())
        self.assertTrue(
            Market.objects.filter(is_enabled=True, is_default=True).exists()
        )


class MarketPricingTests(TestCase):
    def setUp(self):
        ensure_market_catalog()
        invalidate_market_cache()
        self.br = Market.objects.get(code="BR")
        self.gh = Market.objects.get(code="GH")
        self.gh.is_enabled = True
        self.gh.is_default = True
        self.gh.payment_provider = "mock"
        self.gh.payment_methods = ["card", "mobile_money"]
        self.gh.save()
        invalidate_market_cache()

        self.plan = SellerPlan.objects.create(
            code="stress-pro",
            name="Stress Pro",
            monthly_price=Decimal("999.00"),  # legacy/base value must not leak
            yearly_price=Decimal("9999.00"),
            listing_limit=100,
            active=True,
        )
        self.product = PromotionProduct.objects.create(
            code=PromotionProduct.Code.FEATURED,
            name="Stress Featured",
            duration_days=7,
            price=Decimal("777.00"),  # legacy/base value must not leak
            active=True,
        )
        SellerPlanMarketPrice.objects.create(
            market=self.gh,
            plan=self.plan,
            monthly_price=Decimal("123.45"),
            yearly_price=Decimal("1200.00"),
        )
        PromotionProductMarketPrice.objects.create(
            market=self.gh,
            product=self.product,
            price=Decimal("19.50"),
        )

    def test_country_specific_plan_price_does_not_use_legacy_numeric_price(self):
        self.assertEqual(
            seller_plan_price(
                plan=self.plan, country_code="GH", billing_cycle="monthly"
            ),
            Decimal("123.45"),
        )

    def test_country_specific_promotion_price(self):
        self.assertEqual(
            promotion_price(product=self.product, country_code="GH"),
            Decimal("19.50"),
        )

    def test_missing_market_price_does_not_cross_currency_fallback(self):
        self.br.is_enabled = True
        self.br.save()
        invalidate_market_cache()
        SellerPlanMarketPrice.objects.filter(market=self.br, plan=self.plan).delete()
        with self.assertRaises(ValidationError):
            seller_plan_price(
                plan=self.plan, country_code="BR", billing_cycle="monthly"
            )

    def test_pricing_readiness_reports_missing_prices(self):
        ready, issues = market_pricing_readiness(self.gh)
        # Seeded marketplace products/plans may add additional requirements; the
        # stress-specific rows themselves must not be reported missing.
        self.assertNotIn("Missing seller plan price: stress-pro", issues)
        self.assertNotIn("Missing promotion price: featured", issues)
        self.assertEqual(ready, not bool(issues))

    @override_settings(
        MARKETLIFT_PAYMENTS_ENABLED=True,
        PAYMENT_MOCK_AUTO_APPROVE=True,
    )
    def test_payment_uses_market_price_and_currency(self):
        user = User.objects.create_user(
            email="market-price@example.com",
            password="correct horse battery staple",
            full_name="Market Price Tester",
            country_code="GH",
        )
        seller = SellerProfile.objects.create(
            user=user,
            display_name="Market Price Seller",
            country_code="GH",
        )
        payment = create_subscription_payment(
            seller=seller,
            plan=self.plan,
            billing_cycle="monthly",
            method="card",
            idempotency_key="stress-market-price-1",
        )
        self.assertEqual(payment.amount, Decimal("123.45"))
        self.assertEqual(payment.currency, "GHS")
        self.assertEqual(payment.country_code, "GH")
        self.assertEqual(payment.provider, "mock")
