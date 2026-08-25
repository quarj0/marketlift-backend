from unittest.mock import Mock, patch
from marketlift.markets.profiles import get_market_profile
from marketlift.markets.service import invalidate_market_cache
import hashlib
import hmac
import uuid
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from categories.models import Category
from listings.models import Listing
from sellers.models import SellerProfile
from subscriptions.models import SellerPlan, SellerSubscription
from promotions.models import PromotionProduct, ListingPromotion
from platform_settings.market_catalog import ensure_market_catalog
from platform_settings.models import Market, PromotionProductMarketPrice, SellerPlanMarketPrice
from .models import Payment
from .services import (
    create_promotion_payment,
    create_subscription_payment,
    require_payments_enabled,
)
from .webhooks import valid_mercado_pago_signature


@override_settings(MARKETLIFT_PAYMENTS_ENABLED=False)
class PaymentsReleaseGateTests(SimpleTestCase):
    def test_provider_backed_payments_are_dormant_by_default(self):
        with self.assertRaisesMessage(ValidationError, "not available yet"):
            require_payments_enabled()


@override_settings(
    MARKETLIFT_PAYMENTS_ENABLED=True,
    MARKETLIFT_PAYMENT_PROVIDER="mock",
    PAYMENT_MOCK_AUTO_APPROVE=True,
)
class PaymentTests(TestCase):
    def setUp(self):
        ensure_market_catalog()
        U = get_user_model()
        self.user = U.objects.create_user(
            email="pay@example.com", password="testpass123", full_name="Pay Seller"
        )
        self.seller = SellerProfile.objects.create(
            user=self.user, display_name="Pay Shop"
        )
        self.free = SellerPlan.objects.create(code="free", name="Free", listing_limit=5)
        self.pro = SellerPlan.objects.create(
            code="pro",
            name="Pro",
            monthly_price=89.90,
            yearly_price=899,
            listing_limit=100,
            promotion_credits=4,
        )
        self.category = Category.objects.create(
            slug="phones-test",
            name="Phones Test",
            pricing_mode="required",
            condition_enabled=False,
        )
        self.listing = Listing.objects.create(
            seller=self.seller,
            category=self.category,
            title="Phone",
            description="Good phone",
            price=1000,
            state="SP",
            state_code="SP",
            city="Sao Paulo",
            status=Listing.Status.PUBLISHED,
        )
        self.product = PromotionProduct.objects.create(
            code="featured", name="Featured", duration_days=7, price=19.90
        )
        # Payments now require explicit per-market pricing. This deliberately
        # avoids falling back from BRL values into another market's currency.
        market = Market.objects.get(code=self.seller.country_code)
        market.is_enabled = True
        market.is_default = True
        market.payment_provider = "mock"
        market.payment_methods = ["pix", "card", "boleto"]
        market.save()
        # TestCase wraps each test in an outer transaction, so Market.save()'s
        # on_commit cache invalidation does not run until teardown. Clear the
        # runtime market cache explicitly before payment/provider resolution.
        invalidate_market_cache()
        SellerPlanMarketPrice.objects.create(
            market=market,
            plan=self.pro,
            monthly_price=self.pro.monthly_price,
            yearly_price=self.pro.yearly_price,
            active=True,
        )
        PromotionProductMarketPrice.objects.create(
            market=market, product=self.product, price=self.product.price, active=True
        )

    def test_subscription_payment_is_idempotent_and_activates_plan(self):
        key = str(uuid.uuid4())
        p1 = create_subscription_payment(
            seller=self.seller,
            plan=self.pro,
            billing_cycle="monthly",
            method="pix",
            idempotency_key=key,
        )
        p2 = create_subscription_payment(
            seller=self.seller,
            plan=self.pro,
            billing_cycle="monthly",
            method="pix",
            idempotency_key=key,
        )
        self.assertEqual(p1.id, p2.id)
        p1.refresh_from_db()
        self.assertEqual(p1.status, Payment.Status.PAID)
        self.assertIsNotNone(p1.subscription_id)
        sub = SellerSubscription.objects.get(pk=p1.subscription_id)
        self.assertEqual(sub.promotion_credits_remaining, 4)

    def test_promotion_payment_fulfils_once(self):
        p = create_promotion_payment(
            seller=self.seller,
            listing=self.listing,
            product=self.product,
            method="pix",
            idempotency_key=str(uuid.uuid4()),
        )
        p.refresh_from_db()
        self.assertEqual(p.status, Payment.Status.PAID)
        self.assertEqual(
            ListingPromotion.objects.filter(
                listing=self.listing, source="purchase"
            ).count(),
            1,
        )


class MercadoPagoWebhookSignatureTests(TestCase):
    def test_official_manifest_shape_validates(self):
        data_id = "123456"
        request_id = "req-789"
        timestamp = "1755612000"
        secret = "marketlift-test-secret"
        manifest = f"id:{data_id};request-id:{request_id};ts:{timestamp};"
        signature = hmac.new(
            secret.encode(), manifest.encode(), hashlib.sha256
        ).hexdigest()
        self.assertTrue(
            valid_mercado_pago_signature(
                data_id=data_id,
                request_id=request_id,
                signature=f"ts={timestamp},v1={signature}",
                secret=secret,
            )
        )
        self.assertFalse(
            valid_mercado_pago_signature(
                data_id=data_id,
                request_id=request_id,
                signature=f"ts={timestamp},v1=invalid",
                secret=secret,
            )
        )


class PaystackProviderUnitTests(SimpleTestCase):
    @override_settings(
        MARKETLIFT_MARKET_CODE="GH",
        MARKETLIFT_ENABLED_MARKETS=(get_market_profile("GH"),),
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_CALLBACK_URL="https://example.test/payments/callback",
    )
    @patch("payments.providers.paystack.httpx.Client")
    def test_initialize_uses_currency_subunits_and_supported_channel(self, client_cls):
        from types import SimpleNamespace
        from decimal import Decimal
        from payments.providers.paystack import PaystackProvider

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "status": True,
            "message": "Authorization URL created",
            "data": {
                "authorization_url": "https://checkout.paystack.com/example",
                "access_code": "access",
                "reference": "ML-ABC123",
            },
        }
        client = Mock()
        client.request.return_value = response
        client_cls.return_value.__enter__.return_value = client
        payment = SimpleNamespace(
            id="00000000-0000-0000-0000-000000000001",
            amount=Decimal("12.34"),
            currency="GHS",
            reference="ML-ABC123",
            method="mobile_money",
            purpose="promotion",
            seller_id="00000000-0000-0000-0000-000000000002",
        )
        result = PaystackProvider().create_order(
            payment=payment, payer={"email": "seller@example.com"}
        )
        payload = client.request.call_args.kwargs["json"]
        self.assertEqual(payload["amount"], "1234")
        self.assertEqual(payload["currency"], "GHS")
        self.assertEqual(payload["reference"], "ML-ABC123")
        self.assertEqual(payload["channels"], ["mobile_money"])
        self.assertEqual(result.checkout_data["authorization_url"], "https://checkout.paystack.com/example")

    @override_settings(
        MARKETLIFT_MARKET_CODE="CI",
        MARKETLIFT_ENABLED_MARKETS=(get_market_profile("CI"),),
    )
    def test_xof_is_still_sent_to_paystack_multiplied_by_100(self):
        from decimal import Decimal
        from payments.providers.paystack import _subunit

        self.assertEqual(_subunit(Decimal("500"), "XOF"), 50000)

    def test_paystack_webhook_signature_uses_sha512(self):
        import hashlib
        import hmac
        from payments.webhooks import valid_paystack_signature

        body = b'{"event":"charge.success"}'
        secret = "secret"
        signature = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
        self.assertTrue(
            valid_paystack_signature(body=body, signature=signature, secret=secret)
        )
