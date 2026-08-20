from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase

from accounts.models import User
from categories.models import Category, CategoryField
from categories.services import create_category_field, update_category_field
from listings.models import ListingAttribute
from listings.services import create_listing
from sellers.models import SellerProfile


class FlexibleCategoryFieldTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_marketplace_domain", verbosity=0)
        cls.user = User.objects.create_user(
            email="flex-fields@example.com",
            password="password123",
            full_name="Flexible Seller",
            state="São Paulo",
            state_code="SP",
            city="São Paulo",
        )
        cls.seller = SellerProfile.objects.create(
            user=cls.user, display_name="Flexible Seller"
        )
        cls.phones = Category.objects.get(slug="phones")

    def _payload(self, **attributes):
        values = {
            "brand": "Apple",
            "model": "iPhone 15 Pro",
            "storage_gb": 256,
        }
        values.update(attributes)
        return {
            "seller": self.seller,
            "category": self.phones,
            "title": "Flexible phone",
            "description": "A phone used to validate flexible category fields.",
            "price": "1000.00",
            "condition": "Like new",
            "state": "São Paulo",
            "state_code": "SP",
            "city": "São Paulo",
            "attributes": values,
        }

    def test_suggested_select_accepts_label_and_numeric_value_and_canonicalizes(self):
        listing = create_listing(**self._payload())
        values = {
            item.key: item.value
            for item in ListingAttribute.objects.filter(listing=listing)
        }
        self.assertEqual(values["brand"], "apple")
        self.assertEqual(values["storage_gb"], "256")

    def test_suggested_select_accepts_custom_brand_and_storage(self):
        listing = create_listing(**self._payload(brand="Nothing", storage_gb="2048"))
        values = {
            item.key: item.value
            for item in ListingAttribute.objects.filter(listing=listing)
        }
        self.assertEqual(values["brand"], "Nothing")
        self.assertEqual(values["storage_gb"], "2048")

    def test_strict_select_still_rejects_unknown_value(self):
        with self.assertRaises(ValidationError) as context:
            create_listing(**self._payload(sim_type="triple_sim"))
        self.assertIn("sim_type", context.exception.message_dict)

    def test_admin_can_create_suggested_field_and_schema_version_increments(self):
        category = Category.objects.create(
            slug="sports",
            name="Sports",
            pricing_mode=Category.PricingMode.REQUIRED,
        )
        original_version = category.schema_version
        field = create_category_field(
            category=category,
            key="brand",
            label="Brand",
            field_type=CategoryField.FieldType.SELECT,
            required=False,
            filterable=True,
            allow_custom_value=True,
            options=[
                {"value": "nike", "label": "Nike", "sort_order": 0},
                {"value": "adidas", "label": "Adidas", "sort_order": 1},
            ],
        )
        category.refresh_from_db()
        self.assertEqual(category.schema_version, original_version + 1)
        self.assertTrue(field.allow_custom_value)
        self.assertEqual(field.options.count(), 2)

    def test_strict_admin_select_requires_options(self):
        category = Category.objects.create(slug="strict", name="Strict")
        with self.assertRaises(ValidationError):
            create_category_field(
                category=category,
                key="type",
                label="Type",
                field_type=CategoryField.FieldType.SELECT,
                allow_custom_value=False,
                options=[],
            )

    def test_field_key_and_type_become_immutable_after_listing_usage(self):
        listing = create_listing(**self._payload())
        brand = self.phones.fields.get(key="brand")
        self.assertTrue(brand.listing_values.filter(listing=listing).exists())

        with self.assertRaises(ValidationError):
            update_category_field(
                field=brand,
                key="manufacturer",
                label=brand.label,
                field_type=brand.field_type,
                required=brand.required,
                filterable=brand.filterable,
                allow_custom_value=True,
                options=[
                    {"value": o.value, "label": o.label, "sort_order": o.sort_order}
                    for o in brand.options.all()
                ],
            )
