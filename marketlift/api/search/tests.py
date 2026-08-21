from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError as RestValidationError

from marketlift.api.search.params import search_request_from_query_params
from marketlift.search.service import validate_search_request


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
        with self.assertRaises(RestValidationError):
            search_request_from_query_params({"verified_only": "maybe"})

    def test_geospatial_params_are_parsed(self):
        request = search_request_from_query_params(
            {
                "lat": "-23.5505",
                "lng": "-46.6333",
                "radius_km": "10",
                "country_code": "BR",
                "sort": "distance",
            }
        )
        self.assertEqual(request.latitude, -23.5505)
        self.assertEqual(request.longitude, -46.6333)
        self.assertEqual(request.radius_km, 10.0)
        self.assertEqual(request.country_code, "BR")

    def test_brazil_location_hierarchy_is_parsed(self):
        request = search_request_from_query_params(
            {
                "region": "se",
                "state": "sp",
                "city": "São Paulo",
                "neighborhood": "Pinheiros",
            }
        )
        self.assertEqual(request.country_code, "BR")
        self.assertEqual(request.region, "SE")
        self.assertEqual(request.state, "SP")
        self.assertEqual(request.city, "São Paulo")
        self.assertEqual(request.district, "Pinheiros")

    def test_state_must_belong_to_selected_region(self):
        request = search_request_from_query_params({"region": "NE", "state": "SP"})
        with self.assertRaises(DjangoValidationError):
            validate_search_request(request)
