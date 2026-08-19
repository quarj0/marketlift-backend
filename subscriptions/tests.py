from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

from accounts.models import User
from sellers.models import SellerProfile

from .models import SellerPlan, SellerSubscription
from .services import create_seller_plan, get_effective_plan


class SellerPlanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_marketplace_domain", verbosity=0)
        cls.user = User.objects.create_user(
            email="plan@example.com",
            password="password123",
            full_name="Plan Seller",
        )
        cls.seller = SellerProfile.objects.create(user=cls.user)

    def test_free_plan_is_effective_without_paid_subscription(self):
        self.assertEqual(get_effective_plan(self.seller).code, "free")

    def test_active_subscription_overrides_free_plan(self):
        pro = SellerPlan.objects.get(code="pro")
        SellerSubscription.objects.create(seller=self.seller, plan=pro)
        self.assertEqual(get_effective_plan(self.seller).code, "pro")

    def test_expired_subscription_falls_back_to_free_plan(self):
        pro = SellerPlan.objects.get(code="pro")
        SellerSubscription.objects.create(
            seller=self.seller,
            plan=pro,
            current_period_start=timezone.now() - timedelta(days=31),
            current_period_end=timezone.now() - timedelta(minutes=1),
        )
        self.assertEqual(get_effective_plan(self.seller).code, "free")
        self.assertEqual(
            self.seller.subscriptions.get(plan=pro).status,
            SellerSubscription.Status.EXPIRED,
        )

    def test_admin_service_can_create_new_plan(self):
        plan = create_seller_plan(
            code="starter-plus",
            name="Starter Plus",
            monthly_price=49.9,
            yearly_price=499,
            listing_limit=35,
            promotion_credits=2,
        )
        self.assertEqual(plan.code, "starter-plus")
        self.assertEqual(str(plan.monthly_price), "49.90")
