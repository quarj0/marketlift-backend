from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from categories.models import Category
from listings.models import Listing
from listings.services import delete_listing_by_seller
from messaging.models import Conversation
from messaging.services import send_message
from sellers.models import SellerFollow, SellerProfile
from sellers.services import follow_seller


class SellerCompletionTests(TestCase):
    def setUp(self):
        self.seller_user = User.objects.create_user(
            email="seller@example.com",
            password="Example-Secure-482!",
            full_name="Seller",
        )
        self.buyer = User.objects.create_user(
            email="buyer@example.com", password="Example-Secure-482!", full_name="Buyer"
        )
        self.seller = SellerProfile.objects.create(
            user=self.seller_user, display_name="Seller"
        )
        self.category = Category.objects.create(
            slug="test-category", name="Test category"
        )

    def test_follow_is_unique_and_self_follow_is_rejected(self):
        follow_seller(user=self.buyer, seller=self.seller)
        follow_seller(user=self.buyer, seller=self.seller)
        self.assertEqual(
            SellerFollow.objects.filter(
                follower=self.buyer, seller=self.seller
            ).count(),
            1,
        )
        with self.assertRaises(ValidationError):
            follow_seller(user=self.seller_user, seller=self.seller)

    def test_seller_delete_preserves_listing_but_removes_public_visibility(self):
        listing = Listing.objects.create(
            seller=self.seller,
            category=self.category,
            title="Item",
            description="Item",
            state="SP",
            state_code="SP",
            city="Sao Paulo",
            status=Listing.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        self.assertTrue(Listing.objects.public().filter(pk=listing.pk).exists())
        delete_listing_by_seller(listing=listing, reason="No longer selling")
        self.assertTrue(Listing.objects.filter(pk=listing.pk).exists())
        self.assertFalse(Listing.objects.public().filter(pk=listing.pk).exists())

    def test_seller_deleted_listing_closes_existing_conversation_writes(self):
        listing = Listing.objects.create(
            seller=self.seller,
            category=self.category,
            title="Chat item",
            description="Item",
            state="SP",
            state_code="SP",
            city="Sao Paulo",
            status=Listing.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        conversation = Conversation.objects.create(
            listing=listing,
            listing_title_snapshot=listing.title,
            buyer=self.buyer,
            seller=self.seller,
        )
        delete_listing_by_seller(listing=listing)
        with self.assertRaisesMessage(ValidationError, "closed"):
            send_message(user=self.buyer, conversation=conversation, text="Hello")
