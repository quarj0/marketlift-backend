from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from categories.models import Category
from commerce.graphql.mappers import order_to_type
from commerce.models import (
    CommercePayment,
    Order,
    SellerPaymentAccount,
    Settlement,
    Shipment,
)
from commerce.policy_models import CategoryCommercePolicy, ListingCommerceSettings
from commerce.providers.base import CommerceProviderError
from commerce.services import (
    confirm_order_delivered,
    listing_commerce_state,
    withdraw_available_balance,
)
from listings.models import Listing
from sellers.models import SellerProfile


class CommerceServiceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.seller_user = User.objects.create_user(
            email="commerce-seller@example.com",
            password="testpass123",
            full_name="Commerce Seller",
        )
        self.buyer = User.objects.create_user(
            email="commerce-buyer@example.com",
            password="testpass123",
            full_name="Commerce Buyer",
        )
        self.seller = SellerProfile.objects.create(
            user=self.seller_user,
            display_name="Commerce Shop",
            verified_at=timezone.now(),
        )
        self.category = Category.objects.create(
            slug="commerce-test",
            name="Commerce Test",
            pricing_mode="required",
            condition_enabled=False,
        )
        self.listing = Listing.objects.create(
            seller=self.seller,
            category=self.category,
            title="Checkout item",
            description="A commerce test listing",
            price=Decimal("2500.00"),
            state="SP",
            state_code="SP",
            city="Sao Paulo",
            status=Listing.Status.PUBLISHED,
        )
        self.policy = CategoryCommercePolicy.objects.create(
            category=self.category,
            mode=CategoryCommercePolicy.Mode.ENABLED,
            requires_verified_seller=True,
            shipping_allowed=True,
            local_delivery_allowed=True,
            pickup_allowed=True,
        )
        self.listing_config = ListingCommerceSettings.objects.create(
            listing=self.listing,
            checkout_enabled=True,
            stock_quantity=1,
            shipping_enabled=True,
            local_delivery_enabled=True,
            pickup_enabled=True,
        )
        self.payment_account = SellerPaymentAccount.objects.create(
            seller=self.seller,
            provider="stripe",
            provider_recipient_id="rp_test_seller",
            status=SellerPaymentAccount.Status.ACTIVE,
            payout_method=SellerPaymentAccount.PayoutMethod.BANK_ACCOUNT,
            payout_destination_masked="260 •••• 1234",
            payouts_enabled=True,
        )

    def make_order(self, *, paid: bool = False, status: str | None = None):
        paid_at = timezone.now() if paid else None
        order = Order.objects.create(
            reference=f"ML-TEST-{Order.objects.count() + 1}",
            buyer=self.buyer,
            seller=self.seller,
            listing=self.listing,
            status=status
            or (Order.Status.SHIPPED if paid else Order.Status.PENDING_PAYMENT),
            fulfillment_method=Order.FulfillmentMethod.SHIPPING,
            quantity=1,
            unit_price_cents=250000,
            subtotal_cents=250000,
            shipping_amount_cents=0,
            total_cents=250000,
            marketplace_fee_cents=12500,
            seller_proceeds_cents=237500,
            currency="BRL",
            shipping_address={"city": "Sao Paulo", "cep": "04368003"},
            listing_snapshot={"title": "Checkout item", "delivery_pin": "654321"},
            paid_at=paid_at,
        )
        Shipment.objects.create(order=order, status=Shipment.Status.SHIPPED)
        Settlement.objects.create(
            order=order,
            seller=self.seller,
            amount_cents=237500,
            status=Settlement.Status.HELD if paid else Settlement.Status.PENDING,
        )
        CommercePayment.objects.create(
            order=order,
            method=CommercePayment.Method.PIX,
            status=(
                CommercePayment.Status.APPROVED
                if paid
                else CommercePayment.Status.PENDING
            ),
            idempotency_key=f"commerce-test-{order.id}",
            provider_order_id=f"or_{order.id}",
            provider_charge_id=f"ch_{order.id}",
            amount_cents=250000,
            paid_at=paid_at,
        )
        return order

    def test_listing_checkout_requires_active_policy_and_payment_account(self):
        state = listing_commerce_state(self.listing)
        self.assertTrue(state["checkout_enabled"])
        self.assertEqual(
            set(state["fulfillment_methods"]),
            {
                Order.FulfillmentMethod.SHIPPING,
                Order.FulfillmentMethod.LOCAL_DELIVERY,
                Order.FulfillmentMethod.PICKUP,
            },
        )

        self.policy.mode = CategoryCommercePolicy.Mode.DISABLED
        self.policy.save(update_fields=("mode", "updated_at"))
        state = listing_commerce_state(self.listing)
        self.assertFalse(state["checkout_enabled"])
        self.assertIn("category_classified_only", state["reasons"])

    def test_unpaid_order_cannot_be_confirmed_delivered(self):
        order = self.make_order(paid=False)
        with self.assertRaisesMessage(
            ValidationError, "Only a paid order in fulfillment"
        ):
            confirm_order_delivered(order=order, buyer=self.buyer)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)

    @override_settings(MARKETLIFT_BUYER_PROTECTION_HOURS=48)
    def test_paid_delivery_starts_buyer_protection_window(self):
        before = timezone.now()
        order = self.make_order(paid=True)
        confirmed = confirm_order_delivered(order=order, buyer=self.buyer)
        confirmed.refresh_from_db()
        settlement = confirmed.settlement
        settlement.refresh_from_db()

        self.assertEqual(confirmed.status, Order.Status.DELIVERED)
        self.assertEqual(settlement.status, Settlement.Status.HELD)
        self.assertIsNotNone(settlement.release_after)
        self.assertGreaterEqual(settlement.release_after, before + timedelta(hours=47))

    def test_shipping_address_visibility_never_exposes_legacy_delivery_pin(self):
        order = self.make_order(paid=True)
        buyer_view = order_to_type(order, buyer_view=True)
        seller_view = order_to_type(
            order,
            buyer_view=False,
            include_shipping_address=True,
        )
        admin_view = order_to_type(order, buyer_view=False)

        self.assertNotIn("delivery_pin", buyer_view.listing_snapshot)
        self.assertEqual(seller_view.shipping_address["city"], "Sao Paulo")
        self.assertNotIn("delivery_pin", seller_view.listing_snapshot)
        self.assertEqual(admin_view.shipping_address, {})
        self.assertNotIn("delivery_pin", admin_view.listing_snapshot)

    def test_withdrawal_fails_closed_when_provider_balance_is_unknown(self):
        order = self.make_order(paid=True)
        settlement = order.settlement
        settlement.status = Settlement.Status.AVAILABLE
        settlement.release_after = None
        settlement.save(update_fields=("status", "release_after", "updated_at"))

        provider = Mock()
        provider.get_recipient_balance.return_value = {}
        with patch("commerce.services.get_commerce_provider", return_value=provider):
            with self.assertRaisesMessage(
                ValidationError, "balance could not be verified"
            ):
                withdraw_available_balance(seller=self.seller)
        provider.create_transfer.assert_not_called()

    def test_definitive_transfer_failure_requeues_available_settlement(self):
        order = self.make_order(paid=True)
        settlement = order.settlement
        settlement.status = Settlement.Status.AVAILABLE
        settlement.release_after = None
        settlement.save(update_fields=("status", "release_after", "updated_at"))

        provider = Mock()
        provider.get_recipient_balance.return_value = {"available_amount": 500000}
        provider.create_transfer.side_effect = CommerceProviderError(
            "invalid transfer",
            retryable=False,
            status_code=422,
        )
        with patch("commerce.services.get_commerce_provider", return_value=provider):
            with self.assertRaises(CommerceProviderError):
                withdraw_available_balance(seller=self.seller)

        settlement.refresh_from_db()
        self.assertEqual(settlement.status, Settlement.Status.AVAILABLE)
        self.assertEqual(settlement.provider_transfer_id, "")
        self.assertEqual(settlement.payout_idempotency_key, "")
        self.assertIsNone(settlement.payout_requested_at)

    def test_retryable_transfer_failure_preserves_stable_batch_key(self):
        order = self.make_order(paid=True)
        settlement = order.settlement
        settlement.status = Settlement.Status.AVAILABLE
        settlement.release_after = None
        settlement.save(update_fields=("status", "release_after", "updated_at"))

        provider = Mock()
        provider.get_recipient_balance.return_value = {"available_amount": 500000}
        provider.create_transfer.side_effect = CommerceProviderError(
            "provider timeout",
            retryable=True,
        )
        with patch("commerce.services.get_commerce_provider", return_value=provider):
            with self.assertRaises(CommerceProviderError):
                withdraw_available_balance(seller=self.seller)

        settlement.refresh_from_db()
        first_key = settlement.payout_idempotency_key
        self.assertEqual(settlement.status, Settlement.Status.PAYOUT_REQUESTED)
        self.assertTrue(first_key)
        self.assertEqual(settlement.provider_transfer_id, "")

        provider.create_transfer.side_effect = None
        provider.create_transfer.return_value = {
            "id": "tr_retry",
            "status": "pending",
        }
        with patch("commerce.services.get_commerce_provider", return_value=provider):
            payload = withdraw_available_balance(seller=self.seller)

        settlement.refresh_from_db()
        self.assertEqual(payload["transfer_id"], "tr_retry")
        self.assertEqual(settlement.payout_idempotency_key, first_key)
        self.assertEqual(settlement.provider_transfer_id, "tr_retry")
        first_call = provider.create_transfer.call_args_list[0].kwargs
        second_call = provider.create_transfer.call_args_list[1].kwargs
        self.assertEqual(first_call["idempotency_key"], second_call["idempotency_key"])
