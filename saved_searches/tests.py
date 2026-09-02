from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import User
from categories.models import Category, CategoryField
from saved_searches.services import create_saved_search


class SavedSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Attribute-filter validation is intentionally schema-driven. The old
        # camelCase compatibility test used ``brand`` without defining a
        # filterable brand field, which no longer represents a valid marketplace
        # taxonomy after the search hardening work.
        category = Category.objects.create(
            slug="phones",
            name="Phones",
            active=True,
        )
        CategoryField.objects.create(
            category=category,
            key="brand",
            label="Brand",
            field_type=CategoryField.FieldType.SELECT,
            filterable=True,
        )

    def test_normalizes_criteria(self):
        u = User.objects.create_user(email="s@example.com", password="x", full_name="S")
        x = create_saved_search(
            user=u, name="phones", criteria={"q": "iphone", "evil": 1}
        )
        self.assertEqual(x.criteria, {"q": "iphone"})

    def test_accepts_graphql_style_camel_case_criteria(self):
        u = User.objects.create_user(
            email="camel@example.com", password="x", full_name="C"
        )
        x = create_saved_search(
            user=u,
            name="phones",
            criteria={
                "minPrice": 100,
                "maxPrice": 500,
                "verifiedOnly": True,
                "attributeFilters": {"brand": "Apple"},
            },
        )
        self.assertEqual(
            x.criteria,
            {
                "min_price": 100,
                "max_price": 500,
                "verified_only": True,
                "attribute_filters": {"brand": "Apple"},
            },
        )

    def test_rejects_unknown_attribute_filter(self):
        u = User.objects.create_user(
            email="invalid-filter@example.com", password="x", full_name="I"
        )
        with self.assertRaises(ValidationError):
            create_saved_search(
                user=u,
                name="invalid",
                criteria={"attributeFilters": {"not_a_marketplace_field": "x"}},
            )


from django.contrib.auth import get_user_model
from django.test import TestCase
from saved_searches.services import create_saved_search


class SavedSearchIdempotencyTests(TestCase):
    def test_same_saved_search_is_idempotent(self):
        user = get_user_model().objects.create_user(
            email="saved-search-idempotent@example.com",
            full_name="Saved Search",
            password="secret123",
        )
        criteria = {"q": "Samsung 980 1TB", "countryCode": "BR"}
        first = create_saved_search(
            user=user,
            name="SSD alert",
            criteria=criteria,
            alerts_enabled=True,
        )
        second = create_saved_search(
            user=user,
            name="SSD alert",
            criteria=criteria,
            alerts_enabled=True,
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(user.saved_searches.filter(active=True).count(), 1)
