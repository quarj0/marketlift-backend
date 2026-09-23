import json
from datetime import time

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from categories.models import Category
from listings.models import Listing
from listings.services import delete_listing_by_seller
from messaging.models import Conversation
from messaging.services import send_message
from sellers.graphql.mappers import seller_to_type
from sellers.models import SellerFollow, SellerProfile, SellerSettings
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

    def test_store_details_are_exposed_on_public_seller(self):
        self.seller.seller_type = SellerProfile.SellerType.BUSINESS
        self.seller.store_address = "Rua das Flores, 120"
        self.seller.opens_at = time(9, 0)
        self.seller.closes_at = time(18, 30)
        self.seller.save(
            update_fields=(
                "seller_type",
                "store_address",
                "opens_at",
                "closes_at",
                "updated_at",
            )
        )

        public = seller_to_type(self.seller)
        self.assertEqual(public.store_address, "Rua das Flores, 120")
        self.assertEqual(public.opens_at, "09:00")
        self.assertEqual(public.closes_at, "18:30")

    def test_individual_seller_store_details_are_not_public(self):
        self.seller.store_address = "Private address"
        self.seller.opens_at = time(9, 0)
        self.seller.closes_at = time(18, 0)
        self.seller.save(update_fields=("store_address", "opens_at", "closes_at", "updated_at"))

        public = seller_to_type(self.seller)
        self.assertIsNone(public.store_address)
        self.assertIsNone(public.opens_at)
        self.assertIsNone(public.closes_at)

    def test_graphql_updates_store_address_and_working_hours(self):
        self.client.force_login(self.seller_user)
        response = self.client.post(
            "/graphql/",
            data=json.dumps(
                {
                    "query": """
                        mutation UpdateSeller($input: SellerProfileInput!) {
                          updateMySellerProfile(input: $input) {
                            storeAddress
                            opensAt
                            closesAt
                          }
                        }
                    """,
                    "variables": {
                        "input": {
                            "sellerType": "business",
                            "storeAddress": "Av. Paulista, 1000",
                            "opensAt": "08:30",
                            "closesAt": "19:00",
                        }
                    },
                }
            ),
            content_type="application/json",
        )
        payload = response.json()
        self.assertNotIn("errors", payload)
        result = payload["data"]["updateMySellerProfile"]
        self.assertEqual(result["storeAddress"], "Av. Paulista, 1000")
        self.assertEqual(result["opensAt"], "08:30")
        self.assertEqual(result["closesAt"], "19:00")

    def test_graphql_rejects_incomplete_working_hours(self):
        self.client.force_login(self.seller_user)
        response = self.client.post(
            "/graphql/",
            data=json.dumps(
                {
                    "query": """
                        mutation UpdateSeller($input: SellerProfileInput!) {
                          updateMySellerProfile(input: $input) { id }
                        }
                    """,
                    "variables": {"input": {"opensAt": "09:00", "closesAt": ""}},
                }
            ),
            content_type="application/json",
        )
        payload = response.json()
        self.assertEqual(
            payload["errors"][0]["extensions"]["code"],
            "SELLER_VALIDATION_ERROR",
        )

    def test_public_seller_phone_respects_seller_visibility_setting(self):
        self.seller_user.phone = "+5511999999999"
        self.seller_user.save(update_fields=("phone", "updated_at"))
        visible = seller_to_type(self.seller)
        self.assertEqual(visible.phone, "+5511999999999")

        SellerSettings.objects.create(user_profile=self.seller, show_phone=False)
        hidden = seller_to_type(self.seller)
        self.assertIsNone(hidden.phone)
