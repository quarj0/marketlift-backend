from django.contrib.auth import get_user_model
from django.test import TestCase
from categories.models import Category
from listings.models import Listing
from sellers.models import SellerProfile
from subscriptions.models import SellerPlan, SellerSubscription
from subscriptions.services import activate_paid_subscription
from .models import PromotionProduct
from .services import activate_with_plan_credit


class PlanCreditTests(TestCase):
    def test_plan_credit_decrements(self):
        U = get_user_model()
        user = U.objects.create_user(
            email="credit@example.com",
            password="testpass123",
            full_name="Credit Seller",
        )
        seller = SellerProfile.objects.create(user=user)
        plan = SellerPlan.objects.create(
            code="pro-credit",
            name="Pro Credit",
            monthly_price=10,
            yearly_price=100,
            listing_limit=50,
            promotion_credits=2,
        )
        sub = activate_paid_subscription(
            seller=seller, plan=plan, billing_cycle="monthly", actor=user
        )
        cat = Category.objects.create(
            slug="credit-cat",
            name="Credit Cat",
            pricing_mode="required",
            condition_enabled=False,
        )
        listing = Listing.objects.create(
            seller=seller,
            category=cat,
            title="Listing",
            description="x",
            price=10,
            state="SP",
            state_code="SP",
            city="SP",
            status=Listing.Status.PUBLISHED,
        )
        product = PromotionProduct.objects.create(
            code="urgent", name="Urgent", duration_days=7, price=9
        )
        activate_with_plan_credit(seller=seller, listing=listing, product=product)
        sub.refresh_from_db()
        self.assertEqual(sub.promotion_credits_remaining, 1)
