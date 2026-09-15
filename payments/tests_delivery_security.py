from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from categories.models import Category
from commerce.delivery_services import (
    admin_override_delivery,
    assign_delivery_rider,
    confirm_rider_delivery_pin,
    set_delivery_rider_access,
    start_rider_delivery,
)
from commerce.graphql.mappers import order_to_type
from commerce.models import (
    CommercePayment,
    DeliveryAssignment,
    DeliveryConfirmationAttempt,
    Order,
    Settlement,
    Shipment,
)
from commerce.services import confirm_order_delivered
from listings.models import Listing
from sellers.models import SellerProfile


class RiderDeliverySecurityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.seller_user = User.objects.create_user(
            email="rider-seller@example.com",
            password="testpass123",
            full_name="Rider Seller",
        )
        self.buyer = User.objects.create_user(
            email="rider-buyer@example.com",
            password="testpass123",
            full_name="Rider Buyer",
        )
        self.rider_user = User.objects.create_user(
            email="rider@example.com",
            password="testpass123",
            full_name="Delivery Rider",
        )
        self.other_user = User.objects.create_user(
            email="other-rider@example.com",
            password="testpass123",
            full_name="Other Rider",
        )
        self.admin = User.objects.create_superuser(
            email="delivery-admin@example.com",
            password="testpass123",
            full_name="Delivery Admin",
        )
        self.seller = SellerProfile.objects.create(
            user=self.seller_user,
            display_name="Rider Shop",
            verified_at=timezone.now(),
        )
        self.category = Category.objects.create(
            slug="delivery-security",
            name="Delivery Security",
            pricing_mode="required",
            condition_enabled=False,
        )
        self.listing = Listing.objects.create(
            seller=self.seller,
            category=self.category,
            title="Delivered item",
            description="A local delivery test listing",
            price=Decimal("100.00"),
            state="BA",
            state_code="BA",
            city="Vitoria da Conquista",
            status=Listing.Status.PUBLISHED,
        )

    def make_local_order(self, *, pin="123456", status=Order.Status.PROCESSING):
        now = timezone.now()
        order = Order.objects.create(
            reference=f"ML-RIDER-{Order.objects.count() + 1}",
            buyer=self.buyer,
            seller=self.seller,
            listing=self.listing,
            status=status,
            fulfillment_method=Order.FulfillmentMethod.LOCAL_DELIVERY,
            quantity=1,
            unit_price_cents=10000,
            subtotal_cents=10000,
            shipping_amount_cents=1000,
            total_cents=11000,
            marketplace_fee_cents=500,
            seller_proceeds_cents=9500,
            currency="BRL",
            shipping_address={
                "street": "Rua Segura",
                "number": "42",
                "city": "Vitoria da Conquista",
                "state": "BA",
                "cep": "45000000",
            },
            listing_snapshot={"title": "Delivered item"},
            paid_at=now,
        )
        shipment = Shipment.objects.create(
            order=order,
            status=Shipment.Status.SHIPPED,
            delivery_pin_hash=make_password(pin),
        )
        Settlement.objects.create(
            order=order,
            seller=self.seller,
            amount_cents=9500,
            status=Settlement.Status.HELD,
        )
        CommercePayment.objects.create(
            order=order,
            method=CommercePayment.Method.PIX,
            status=CommercePayment.Status.APPROVED,
            idempotency_key=f"rider-test-{order.id}",
            amount_cents=11000,
            paid_at=now,
        )
        # Reproduce the checkout service's legacy final save. The post-save
        # security hook must encrypt and scrub this value synchronously.
        order.listing_snapshot = {"title": "Delivered item", "delivery_pin": pin}
        order.save(update_fields=("listing_snapshot", "updated_at"))
        order.refresh_from_db()
        shipment.refresh_from_db()
        return order, shipment

    def assign(self, order):
        rider = set_delivery_rider_access(
            user=self.rider_user,
            actor=self.admin,
            active=True,
        )
        assign_delivery_rider(
            order=order,
            rider=rider,
            actor=self.admin,
        )
        return rider

    def test_plaintext_delivery_pin_is_scrubbed_and_only_buyer_can_read_it(self):
        order, _ = self.make_local_order()
        self.assertNotIn("delivery_pin", order.listing_snapshot)
        assignment = DeliveryAssignment.objects.get(shipment__order=order)
        self.assertTrue(assignment.delivery_pin_ciphertext)
        self.assertNotIn("123456", assignment.delivery_pin_ciphertext)

        buyer_view = order_to_type(order, buyer_view=True)
        seller_view = order_to_type(
            order, buyer_view=False, include_shipping_address=True
        )
        self.assertEqual(buyer_view.shipment.delivery_pin, "123456")
        self.assertIsNone(seller_view.shipment.delivery_pin)
        self.assertNotIn("delivery_pin", seller_view.listing_snapshot)

    def test_generic_buyer_confirmation_cannot_bypass_rider_for_local_delivery(self):
        order, _ = self.make_local_order(status=Order.Status.SHIPPED)
        with self.assertRaisesMessage(
            ValidationError,
            "Local delivery must be confirmed by the assigned rider",
        ):
            confirm_order_delivered(order=order, buyer=self.buyer)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.SHIPPED)

    def test_only_assigned_rider_can_start_delivery(self):
        order, shipment = self.make_local_order()
        self.assign(order)
        set_delivery_rider_access(
            user=self.other_user,
            actor=self.admin,
            active=True,
        )
        with self.assertRaisesMessage(ValidationError, "not assigned"):
            start_rider_delivery(order=order, rider_user=self.other_user)

        started = start_rider_delivery(order=order, rider_user=self.rider_user)
        started.refresh_from_db()
        shipment.refresh_from_db()
        self.assertEqual(started.status, Order.Status.OUT_FOR_DELIVERY)
        self.assertEqual(shipment.status, Shipment.Status.OUT_FOR_DELIVERY)

    def test_failed_pin_attempts_persist_and_lock_after_five(self):
        order, _ = self.make_local_order()
        self.assign(order)
        start_rider_delivery(order=order, rider_user=self.rider_user)

        for _ in range(5):
            with self.assertRaises(ValidationError):
                confirm_rider_delivery_pin(
                    order=order,
                    rider_user=self.rider_user,
                    delivery_pin="000000",
                )

        assignment = DeliveryAssignment.objects.get(shipment__order=order)
        self.assertEqual(assignment.delivery_pin_failure_count, 5)
        self.assertIsNotNone(assignment.delivery_pin_locked_until)
        self.assertEqual(
            DeliveryConfirmationAttempt.objects.filter(
                assignment=assignment,
                success=False,
                reason="invalid_pin",
            ).count(),
            5,
        )
        with self.assertRaisesMessage(ValidationError, "Too many incorrect attempts"):
            confirm_rider_delivery_pin(
                order=order,
                rider_user=self.rider_user,
                delivery_pin="123456",
            )

    @override_settings(MARKETLIFT_BUYER_PROTECTION_HOURS=48)
    def test_correct_pin_delivers_and_clears_pin_credentials(self):
        order, shipment = self.make_local_order()
        rider = self.assign(order)
        start_rider_delivery(order=order, rider_user=self.rider_user)
        delivered = confirm_rider_delivery_pin(
            order=order,
            rider_user=self.rider_user,
            delivery_pin="123456",
        )
        delivered.refresh_from_db()
        shipment.refresh_from_db()
        assignment = DeliveryAssignment.objects.get(shipment=shipment)
        settlement = Settlement.objects.get(order=order)

        self.assertEqual(delivered.status, Order.Status.DELIVERED)
        self.assertEqual(shipment.status, Shipment.Status.DELIVERED)
        self.assertEqual(shipment.delivery_pin_hash, "")
        self.assertEqual(assignment.delivery_pin_ciphertext, "")
        self.assertEqual(assignment.rider_id, rider.id)
        self.assertEqual(assignment.delivered_by_id, self.rider_user.id)
        self.assertEqual(
            assignment.confirmation_source,
            DeliveryAssignment.ConfirmationSource.RIDER_PIN,
        )
        self.assertEqual(settlement.status, Settlement.Status.HELD)
        self.assertIsNotNone(settlement.release_after)
        self.assertEqual(
            DeliveryConfirmationAttempt.objects.filter(
                assignment=assignment, success=True
            ).count(),
            1,
        )
        buyer_view = order_to_type(delivered, buyer_view=True)
        self.assertIsNone(buyer_view.shipment.delivery_pin)

    def test_disabling_rider_with_active_delivery_is_blocked(self):
        order, _ = self.make_local_order()
        self.assign(order)
        start_rider_delivery(order=order, rider_user=self.rider_user)
        with self.assertRaisesMessage(ValidationError, "out for delivery"):
            set_delivery_rider_access(
                user=self.rider_user,
                actor=self.admin,
                active=False,
            )

    def test_admin_override_requires_clear_reason_and_is_audited(self):
        order, shipment = self.make_local_order()
        with self.assertRaises(ValidationError):
            admin_override_delivery(
                order=order,
                actor=self.admin,
                reason="short",
            )
        delivered = admin_override_delivery(
            order=order,
            actor=self.admin,
            reason="Buyer called support and confirmed handoff after rider device failure.",
        )
        delivered.refresh_from_db()
        assignment = DeliveryAssignment.objects.get(shipment=shipment)
        self.assertEqual(delivered.status, Order.Status.DELIVERED)
        self.assertEqual(
            assignment.confirmation_source,
            DeliveryAssignment.ConfirmationSource.ADMIN_OVERRIDE,
        )
        self.assertEqual(assignment.delivered_by_id, self.admin.id)
        self.assertNotIn("123456", str(shipment.proof))
