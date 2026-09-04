from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase

from accounts.models import User
from categories.models import Category
from promotions.models import PromotionProduct
from sellers.models import SellerProfile
from subscriptions.models import SellerPlan

from .models import Listing
from .services import create_listing, publish_listing, update_listing


class MarketplaceDomainTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_marketplace_domain", verbosity=0)
        cls.user = User.objects.create_user(
            email="seller@example.com",
            password="password123",
            full_name="Seller Example",
            state="São Paulo",
            state_code="SP",
            city="São Paulo",
        )
        cls.seller = SellerProfile.objects.create(
            user=cls.user, display_name="Seller Example"
        )
        cls.category = Category.objects.get(slug="phones")

    def listing_payload(self, title="iPhone 15 Pro"):
        return {
            "seller": self.seller,
            "category": self.category,
            "title": title,
            "description": "Well maintained phone with original box.",
            "price": "5790.00",
            "condition": Listing.Condition.LIKE_NEW,
            "state": "São Paulo",
            "state_code": "SP",
            "city": "São Paulo",
            "attributes": {
                "brand": "apple",
                "model": "iPhone 15 Pro",
                "storage_gb": "256",
            },
            "image_urls": [
                f"https://example.com/phone-{index}.jpg" for index in range(5)
            ],
        }

    def test_seed_matches_frontend_domain_counts(self):
        self.assertEqual(Category.objects.count(), 13)
        self.assertEqual(
            sum(category.fields.count() for category in Category.objects.all()), 99
        )
        self.assertEqual(SellerPlan.objects.count(), 4)
        self.assertEqual(PromotionProduct.objects.count(), 4)

    def test_listing_validates_dynamic_required_fields(self):
        payload = self.listing_payload()
        payload["attributes"] = {"brand": "apple"}

        with self.assertRaises(ValidationError):
            create_listing(**payload)

    def test_listing_can_publish_and_category_delete_removes_public_visibility(self):
        listing = create_listing(**self.listing_payload())
        publish_listing(listing)

        self.assertEqual(listing.status, Listing.Status.PUBLISHED)
        self.assertTrue(Listing.objects.public().filter(pk=listing.pk).exists())

        self.category.delete()
        listing.refresh_from_db()

        self.assertIsNone(listing.category_id)
        self.assertEqual(listing.category_slug_snapshot, "phones")
        self.assertFalse(Listing.objects.public().filter(pk=listing.pk).exists())

    def test_free_plan_listing_limit_is_enforced(self):
        for index in range(5):
            listing = create_listing(**self.listing_payload(title=f"Phone {index}"))
            publish_listing(listing)

        sixth = create_listing(**self.listing_payload(title="Phone 6"))
        with self.assertRaises(ValidationError):
            publish_listing(sixth)

    def test_rejected_listing_is_final_for_seller_editing(self):
        listing = create_listing(**self.listing_payload())
        listing.status = Listing.Status.REJECTED
        listing.save(update_fields=("status", "updated_at"))

        with self.assertRaises(ValidationError):
            update_listing(
                listing=listing,
                category=self.category,
                title="Changed title",
                description=listing.description,
                price=listing.price,
                condition=listing.condition,
                state=listing.state,
                state_code=listing.state_code,
                city=listing.city,
                attributes={
                    "brand": "apple",
                    "model": "iPhone 15 Pro",
                    "storage_gb": "256",
                },
            )

        with self.assertRaises(ValidationError):
            publish_listing(listing)

    def test_listing_rejects_non_brazilian_state_code(self):
        payload = self.listing_payload()
        payload.update(state="Georgia", state_code="GA", city="Accra")
        with self.assertRaises(ValidationError):
            create_listing(**payload)
