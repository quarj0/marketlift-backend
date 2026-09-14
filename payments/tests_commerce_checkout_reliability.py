import json
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from categories.models import Category
from commerce.models import CommercePayment, Order, SellerPaymentAccount
from commerce.policy_models import CategoryCommercePolicy, ListingCommerceSettings
from commerce.providers.base import CommerceProviderError
from commerce.services import create_checkout_order
from commerce.webhooks import process_pagarme_event
from listings.models import Listing
from sellers.models import SellerProfile


@override_settings(PAGARME_MARKETPLACE_RECIPIENT_ID="rp_marketplace")
class DurableCheckoutTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.seller_user = User.objects.create_user(
            email="durable-seller@example.com",
            password="testpass123",
            full_name="Durable Seller",
        )
        self.buyer = User.objects.create_user(
            email="durable-buyer@example.com",
            password="testpass123",
            full_name="Durable Buyer",
        )
        self.seller = SellerProfile.objects.create(
            user=self.seller_user,
            display_name="Durable Shop",
            verified_at=timezone.now(),
            country_code="BR",
        )
        self.category = Category.objects.create(
            slug="durable-commerce-test",
            name="Durable Commerce Test",
            pricing_mode="required",
            condition_enabled=False,
        )
        self.listing = Listing.objects.create(
            seller=self.seller,
            category=self.category,
            title="Durable checkout item",
            description="Test item",
            price=Decimal("100.00"),
            state="SP",
            state_code="SP",
            city="Sao Paulo",
            status=Listing.Status.PUBLISHED,
        )
        CategoryCommercePolicy.objects.create(
            category=self.category,
            mode=CategoryCommercePolicy.Mode.ENABLED,
            requires_verified_seller=True,
            pickup_allowed=True,
        )
        self.config = ListingCommerceSettings.objects.create(
            listing=self.listing,
            checkout_enabled=True,
            stock_quantity=1,
            pickup_enabled=True,
        )
        SellerPaymentAccount.objects.create(
            seller=self.seller,
            provider="pagarme",
            provider_recipient_id="rp_seller",
            status=SellerPaymentAccount.Status.ACTIVE,
            payout_method=SellerPaymentAccount.PayoutMethod.BANK_ACCOUNT,
            payouts_enabled=True,
        )

    def checkout(self, *, key: str):
        return create_checkout_order(
            buyer=self.buyer,
            listing_id=self.listing.id,
            quantity=1,
            fulfillment_method=Order.FulfillmentMethod.PICKUP,
            shipping_address={},
            payment_method=CommercePayment.Method.PIX,
            customer_document="12345678901",
            customer_phone="11999999999",
            card_id=None,
            idempotency_key=key,
        )

    def test_ambiguous_provider_failure_keeps_durable_reservation_for_same_key_retry(self):
        provider = Mock()
        provider.create_order.side_effect = CommerceProviderError(
            "provider timeout", retryable=True
        )

        with patch(
            "commerce.checkout_reliability.get_commerce_provider",
            return_value=provider,
        ):
            with self.assertRaises(CommerceProviderError):
                self.checkout(key="same-attempt")

        self.config.refresh_from_db()
        self.assertEqual(self.config.stock_quantity, 0)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(CommercePayment.objects.count(), 1)
        first_order = Order.objects.get()
        self.assertEqual(first_order.status, Order.Status.PENDING_PAYMENT)

        provider.create_order.side_effect = None
        provider.create_order.return_value = {
            "id": "or_retry",
            "status": "pending",
            "charges": [
                {
                    "id": "ch_retry",
                    "status": "pending",
                    "last_transaction": {
                        "id": "tx_retry",
                        "qr_code": "pix-copy-code",
                        "qr_code_url": "https://api.pagar.me/core/v5/qrcode.png",
                    },
                }
            ],
        }
        with patch(
            "commerce.checkout_reliability.get_commerce_provider",
            return_value=provider,
        ):
            retried_order, retried_payment = self.checkout(key="same-attempt")

        self.assertEqual(retried_order.id, first_order.id)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(CommercePayment.objects.count(), 1)
        self.assertEqual(retried_payment.provider_order_id, "or_retry")
        self.assertEqual(retried_payment.provider_charge_id, "ch_retry")
        self.config.refresh_from_db()
        self.assertEqual(self.config.stock_quantity, 0)
        self.assertEqual(provider.create_order.call_count, 2)

    def test_webhook_metadata_recovers_payment_when_checkout_response_was_lost(self):
        provider = Mock()
        provider.create_order.side_effect = CommerceProviderError(
            "provider timeout", retryable=True
        )
        with patch(
            "commerce.checkout_reliability.get_commerce_provider",
            return_value=provider,
        ):
            with self.assertRaises(CommerceProviderError):
                self.checkout(key="lost-response")

        order = Order.objects.get()
        payment = CommercePayment.objects.get(order=order)
        self.assertFalse(payment.provider_order_id)
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)

        payload = {
            "id": "hook_lost_response_paid",
            "type": "order.paid",
            "data": {
                "id": "or_recovered",
                "status": "paid",
                "metadata": {"marketlift_order_id": str(order.id)},
                "charges": [
                    {
                        "id": "ch_recovered",
                        "status": "paid",
                        "last_transaction": {"id": "tx_recovered"},
                    }
                ],
            },
        }
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.assertTrue(process_pagarme_event(payload, raw))

        order.refresh_from_db()
        payment.refresh_from_db()
        self.config.refresh_from_db()
        self.assertEqual(order.status, Order.Status.AWAITING_SELLER)
        self.assertEqual(payment.status, CommercePayment.Status.APPROVED)
        self.assertEqual(payment.provider_order_id, "or_recovered")
        self.assertEqual(payment.provider_charge_id, "ch_recovered")
        self.assertEqual(payment.provider_transaction_id, "tx_recovered")
        self.assertEqual(self.config.stock_quantity, 0)

    def test_definitive_provider_rejection_cancels_order_and_restores_stock(self):
        provider = Mock()
        provider.create_order.side_effect = CommerceProviderError(
            "invalid provider request",
            retryable=False,
            status_code=422,
        )

        with patch(
            "commerce.checkout_reliability.get_commerce_provider",
            return_value=provider,
        ):
            order, payment = self.checkout(key="definitive-failure")

        order.refresh_from_db()
        payment.refresh_from_db()
        self.config.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(payment.status, CommercePayment.Status.FAILED)
        self.assertEqual(payment.provider_status, "request_failed_422")
        self.assertEqual(self.config.stock_quantity, 1)
