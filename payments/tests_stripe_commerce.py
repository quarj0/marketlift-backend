import json
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from categories.models import Category
from commerce.models import CommercePayment, Order, SellerPaymentAccount, Settlement
from commerce.policy_models import CategoryCommercePolicy, ListingCommerceSettings
from commerce.providers.base import CommerceProviderError
from commerce.stripe_runtime import (
    activate_seller_payments,
    create_checkout_order,
    withdraw_available_balance,
)
from commerce.stripe_webhooks import process_stripe_event
from listings.models import Listing
from sellers.models import SellerProfile


class StripeCommerceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.seller_user = User.objects.create_user(
            email="stripe-seller@example.com",
            password="testpass123",
            full_name="Stripe Seller",
        )
        self.buyer = User.objects.create_user(
            email="stripe-buyer@example.com",
            password="testpass123",
            full_name="Stripe Buyer",
        )
        self.seller = SellerProfile.objects.create(
            user=self.seller_user,
            display_name="Stripe Shop",
            country_code="BR",
        )
        self.category = Category.objects.create(
            slug="stripe-commerce-test",
            name="Stripe Commerce Test",
            pricing_mode="required",
            condition_enabled=False,
        )
        CategoryCommercePolicy.objects.create(
            category=self.category,
            mode=CategoryCommercePolicy.Mode.ENABLED,
            requires_verified_seller=True,
            pickup_allowed=True,
        )
        self.listing = Listing.objects.create(
            seller=self.seller,
            category=self.category,
            title="Stripe checkout item",
            description="Test item",
            price=Decimal("100.00"),
            state="SP",
            state_code="SP",
            city="Sao Paulo",
            status=Listing.Status.PUBLISHED,
        )
        ListingCommerceSettings.objects.create(
            listing=self.listing,
            checkout_enabled=True,
            stock_quantity=2,
            pickup_enabled=True,
        )

    def _activate_with_stripe_webhook(self):
        provider = Mock()
        provider.code = "stripe"
        provider.create_recipient.return_value = {
            "id": "acct_test_seller",
            "details_submitted": False,
            "charges_enabled": False,
            "payouts_enabled": False,
            "requirements": {},
        }
        provider.create_kyc_link.return_value = {
            "url": "https://connect.stripe.test/onboarding"
        }
        with patch("commerce.stripe_runtime.get_commerce_provider", return_value=provider):
            account = activate_seller_payments(
                seller=self.seller,
                recipient_payload={},
                payout_method="bank_account",
            )

        self.assertEqual(account.provider, "stripe")
        self.assertEqual(account.provider_recipient_id, "acct_test_seller")
        self.assertEqual(account.status, SellerPaymentAccount.Status.PENDING)
        self.assertFalse(account.payouts_enabled)
        self.assertIn("connect.stripe.test", account.kyc_url)

        payload = {
            "id": "evt_account_updated",
            "type": "account.updated",
            "data": {
                "object": {
                    "object": "account",
                    "id": "acct_test_seller",
                    "details_submitted": True,
                    "charges_enabled": True,
                    "payouts_enabled": True,
                    "requirements": {},
                }
            },
        }
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.assertTrue(process_stripe_event(payload, raw))

        account.refresh_from_db()
        self.seller.refresh_from_db()
        self.assertEqual(account.status, SellerPaymentAccount.Status.ACTIVE)
        self.assertTrue(account.payouts_enabled)
        self.assertIsNotNone(self.seller.verified_at)
        return account

    def test_connect_onboarding_can_satisfy_commerce_seller_verification(self):
        self._activate_with_stripe_webhook()

    def test_hosted_checkout_and_payment_intent_webhook_approve_order(self):
        self._activate_with_stripe_webhook()
        provider = Mock()
        provider.code = "stripe"
        provider.create_order.return_value = {
            "id": "cs_test_marketlift",
            "object": "checkout.session",
            "status": "open",
            "payment_status": "unpaid",
            "url": "https://checkout.stripe.com/c/pay/cs_test_marketlift",
            "payment_intent": None,
        }

        with patch("commerce.stripe_runtime.get_commerce_provider", return_value=provider):
            order, payment = create_checkout_order(
                buyer=self.buyer,
                listing_id=self.listing.id,
                quantity=1,
                fulfillment_method=Order.FulfillmentMethod.PICKUP,
                shipping_address={},
                payment_method=CommercePayment.Method.CARD,
                customer_document="",
                customer_phone="",
                card_id=None,
                idempotency_key="stripe-hosted-checkout",
            )

        self.assertEqual(payment.provider, "stripe")
        self.assertEqual(payment.provider_order_id, "cs_test_marketlift")
        self.assertEqual(
            payment.checkout_data["checkout_url"],
            "https://checkout.stripe.com/c/pay/cs_test_marketlift",
        )
        sent = provider.create_order.call_args.kwargs["payload"]
        self.assertEqual(sent["payment_method"], "card")
        self.assertEqual(sent["metadata"]["marketlift_order_id"], str(order.id))
        self.assertEqual(sum(i["amount"] * i["quantity"] for i in sent["items"]), 10000)

        webhook = {
            "id": "evt_payment_intent_succeeded",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "object": "payment_intent",
                    "id": "pi_marketlift",
                    "status": "succeeded",
                    "latest_charge": "ch_marketlift",
                    "metadata": {"marketlift_order_id": str(order.id)},
                }
            },
        }
        raw = json.dumps(webhook, sort_keys=True).encode("utf-8")
        self.assertTrue(process_stripe_event(webhook, raw))

        order.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(order.status, Order.Status.AWAITING_SELLER)
        self.assertEqual(payment.status, CommercePayment.Status.APPROVED)
        self.assertEqual(payment.provider_transaction_id, "pi_marketlift")
        self.assertEqual(payment.provider_charge_id, "ch_marketlift")


    def test_card_decline_webhook_keeps_hosted_checkout_retryable(self):
        self._activate_with_stripe_webhook()
        provider = Mock()
        provider.code = "stripe"
        provider.create_order.return_value = {
            "id": "cs_retryable",
            "object": "checkout.session",
            "status": "open",
            "payment_status": "unpaid",
            "url": "https://checkout.stripe.com/c/pay/cs_retryable",
            "payment_intent": "pi_retryable",
        }
        with patch("commerce.stripe_runtime.get_commerce_provider", return_value=provider):
            order, payment = create_checkout_order(
                buyer=self.buyer,
                listing_id=self.listing.id,
                quantity=1,
                fulfillment_method=Order.FulfillmentMethod.PICKUP,
                shipping_address={},
                payment_method=CommercePayment.Method.CARD,
                customer_document="",
                customer_phone="",
                card_id=None,
                idempotency_key="stripe-retryable-card",
            )

        payload = {
            "id": "evt_retryable_decline",
            "type": "payment_intent.payment_failed",
            "data": {
                "object": {
                    "object": "payment_intent",
                    "id": "pi_retryable",
                    "status": "requires_payment_method",
                    "metadata": {"marketlift_order_id": str(order.id)},
                    "last_payment_error": {"message": "Your card was declined."},
                }
            },
        }
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.assertTrue(process_stripe_event(payload, raw))

        order.refresh_from_db()
        payment.refresh_from_db()
        self.listing.commerce_settings.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)
        self.assertEqual(payment.status, CommercePayment.Status.PENDING)
        self.assertEqual(payment.provider_status, "payment_failed_retryable")
        self.assertEqual(self.listing.commerce_settings.stock_quantity, 1)

    def test_definitive_stripe_transfer_failure_requeues_available_balance(self):
        self._activate_with_stripe_webhook()
        order = Order.objects.create(
            reference="ML-STRIPE-REJECTED-PAYOUT",
            buyer=self.buyer,
            seller=self.seller,
            listing=self.listing,
            status=Order.Status.COMPLETED,
            fulfillment_method=Order.FulfillmentMethod.PICKUP,
            quantity=1,
            unit_price_cents=10000,
            subtotal_cents=10000,
            total_cents=10000,
            marketplace_fee_cents=500,
            seller_proceeds_cents=9500,
            currency="BRL",
            shipping_address={},
            listing_snapshot={"title": self.listing.title},
            paid_at=timezone.now(),
            delivered_at=timezone.now(),
            completed_at=timezone.now(),
        )
        settlement = Settlement.objects.create(
            order=order,
            seller=self.seller,
            status=Settlement.Status.AVAILABLE,
            amount_cents=9500,
            release_after=timezone.now(),
        )
        provider = Mock()
        provider.code = "stripe"
        provider.create_transfer.side_effect = CommerceProviderError(
            "destination is not ready",
            retryable=False,
            status_code=400,
        )

        with patch("commerce.stripe_runtime.get_commerce_provider", return_value=provider):
            with self.assertRaises(CommerceProviderError):
                withdraw_available_balance(seller=self.seller)

        settlement.refresh_from_db()
        self.assertEqual(settlement.status, Settlement.Status.AVAILABLE)
        self.assertEqual(settlement.payout_idempotency_key, "")
        self.assertIsNone(settlement.payout_requested_at)

    def test_release_transfers_only_available_settlements_to_connected_account(self):
        self._activate_with_stripe_webhook()
        order = Order.objects.create(
            reference="ML-STRIPE-PAYOUT",
            buyer=self.buyer,
            seller=self.seller,
            listing=self.listing,
            status=Order.Status.COMPLETED,
            fulfillment_method=Order.FulfillmentMethod.PICKUP,
            quantity=1,
            unit_price_cents=10000,
            subtotal_cents=10000,
            total_cents=10000,
            marketplace_fee_cents=500,
            seller_proceeds_cents=9500,
            currency="BRL",
            shipping_address={},
            listing_snapshot={"title": self.listing.title},
            paid_at=timezone.now(),
            delivered_at=timezone.now(),
            completed_at=timezone.now(),
        )
        settlement = Settlement.objects.create(
            order=order,
            seller=self.seller,
            status=Settlement.Status.AVAILABLE,
            amount_cents=9500,
            release_after=timezone.now(),
        )

        provider = Mock()
        provider.code = "stripe"
        provider.create_transfer.return_value = {
            "id": "tr_marketlift",
            "status": "succeeded",
        }
        with patch("commerce.stripe_runtime.get_commerce_provider", return_value=provider):
            result = withdraw_available_balance(seller=self.seller)

        settlement.refresh_from_db()
        self.assertEqual(result["transfer_id"], "tr_marketlift")
        self.assertEqual(settlement.status, Settlement.Status.PAID)
        self.assertEqual(settlement.provider_transfer_id, "tr_marketlift")
        self.assertIsNotNone(settlement.paid_at)
        provider.get_recipient_balance.assert_not_called()
        provider.create_transfer.assert_called_once()
