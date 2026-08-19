from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import User
from messaging.models import Conversation
from reviews.services import create_review, seller_reputation
from sellers.models import SellerProfile


class ReviewTests(TestCase):
    def setUp(self):
        self.buyer = User.objects.create_user(
            email="buyer@example.com", password="x", full_name="Buyer"
        )
        self.seller_user = User.objects.create_user(
            email="seller@example.com", password="x", full_name="Seller"
        )
        self.seller = SellerProfile.objects.create(user=self.seller_user)

    def test_review_requires_marketplace_interaction(self):
        with self.assertRaisesMessage(ValidationError, "interacted"):
            create_review(
                reviewer=self.buyer,
                seller=self.seller,
                rating=5,
                comment="Great seller experience",
            )

    def test_review_updates_reputation_after_interaction(self):
        Conversation.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            listing_title_snapshot="Marketplace interaction",
        )
        create_review(
            reviewer=self.buyer,
            seller=self.seller,
            rating=5,
            comment="Great seller experience",
        )
        self.assertEqual(seller_reputation(self.seller)["average"], 5.0)
