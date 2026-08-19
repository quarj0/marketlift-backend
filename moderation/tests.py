from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from categories.models import Category
from listings.models import Listing
from moderation.models import ModerationCase
from moderation.services import (
    approve_listing_case,
    move_listing_to_review,
    reject_listing_case,
    remove_listing,
)
from sellers.models import SellerProfile

User = get_user_model()


class ModerationDecisionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin@example.com", password="pass", full_name="Admin", is_staff=True
        )
        self.user = User.objects.create_user(
            email="seller@example.com", password="pass", full_name="Seller"
        )
        self.seller = SellerProfile.objects.create(user=self.user)
        self.category = Category.objects.create(
            slug="test-cat",
            name="Test",
            pricing_mode="optional",
            pricing_label="Price",
            condition_enabled=False,
        )
        self.listing = Listing.objects.create(
            seller=self.seller,
            category=self.category,
            title="Item",
            description="Desc",
            state="SP",
            state_code="SP",
            city="Sao Paulo",
            status=Listing.Status.PUBLISHED,
        )

    def test_approve_is_final_against_reject(self):
        move_listing_to_review(listing=self.listing, actor=self.admin, reason="check")
        approve_listing_case(listing=self.listing, actor=self.admin)
        with self.assertRaises(ValidationError):
            reject_listing_case(
                listing=self.listing, actor=self.admin, reason="opposite"
            )

    def test_removed_listing_not_public(self):
        remove_listing(listing=self.listing, actor=self.admin, reason="policy")
        self.assertFalse(Listing.objects.public().filter(pk=self.listing.pk).exists())
