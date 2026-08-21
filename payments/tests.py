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
from .models import Payment
from .services import create_promotion_payment, create_subscription_payment, require_payments_enabled
from .webhooks import valid_mercado_pago_signature


@override_settings(MARKETLIFT_PAYMENTS_ENABLED=False)
class PaymentsReleaseGateTests(SimpleTestCase):
    def test_provider_backed_payments_are_dormant_by_default(self):
        with self.assertRaisesMessage(ValidationError, "not available yet"):
            require_payments_enabled()


@override_settings(MARKETLIFT_PAYMENTS_ENABLED=True, MARKETLIFT_PAYMENT_PROVIDER="mock", PAYMENT_MOCK_AUTO_APPROVE=True)
class PaymentTests(TestCase):
    def setUp(self):
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
