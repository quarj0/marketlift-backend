from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from categories.models import Category, CategoryField
from marketlift.search.contracts import SearchRequest
from marketlift.search.service import validate_search_request


class SearchRequestValidationTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(
            slug="phones-search-test", name="Phones Search Test"
        )
        CategoryField.objects.create(
            category=self.category,
            key="ram_gb",
            label="RAM",
            field_type=CategoryField.FieldType.NUMBER,
            filterable=True,
        )

    def test_filterable_category_attribute_is_allowed(self):
        request = validate_search_request(
            SearchRequest(
                category=self.category.slug,
                attribute_filters={"ram_gb": {"min": "8"}},
            )
        )
        self.assertEqual(request.attribute_filters["ram_gb"]["min"], Decimal("8"))

    def test_unknown_attribute_is_rejected(self):
        with self.assertRaises(ValidationError):
            validate_search_request(
                SearchRequest(
                    category=self.category.slug,
                    attribute_filters={"user__password": "x"},
                )
            )

    def test_page_size_is_bounded(self):
        with self.assertRaises(ValidationError):
            validate_search_request(SearchRequest(page_size=999))

    def test_unknown_brazilian_region_is_rejected(self):
        with self.assertRaises(ValidationError):
            validate_search_request(SearchRequest(region="XX"))
