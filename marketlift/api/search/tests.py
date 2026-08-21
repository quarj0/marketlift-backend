from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from marketlift.api.search.params import search_request_from_query_params


class SearchQueryParamTests(SimpleTestCase):
    def test_dynamic_attributes_are_parsed(self):
        request = search_request_from_query_params(
            {
                "q": "samsung s21",
                "attr.brand": "samsung",
                "attr.ram_gb.min": "8",
                "page_size": "24",
            }
        )
        self.assertEqual(request.q, "samsung s21")
        self.assertEqual(request.attribute_filters["brand"], "samsung")
        self.assertEqual(request.attribute_filters["ram_gb"]["min"], "8")

    def test_bad_boolean_is_rejected(self):
        with self.assertRaises(ValidationError):
            search_request_from_query_params({"verified_only": "maybe"})
