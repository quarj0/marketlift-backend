from django.core.management import call_command
from django.test import TestCase

from accounts.models import User
from sellers.models import SellerProfile

from .models import SellerPlan, SellerSubscription
from .services import get_effective_plan


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
