from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

from marketlift.search.contracts import SearchPage, SearchRequest
from marketlift.search.service import search_listings


class _CapturingBackend:
    def __init__(self):
        self.request = None
        self.parsed = None

    def search(self, request, parsed):
        self.request = request
        self.parsed = parsed
        return SearchPage([], 0, None, parsed)


class NearMeSearchTests(SimpleTestCase):
    def test_near_me_requires_coordinates(self):
        with self.assertRaises(ValidationError):
            search_listings(SearchRequest(q="iphone perto de mim"))

    @override_settings(MARKETLIFT_SEARCH_NEAR_ME_DEFAULT_RADIUS_KM=25)
    def test_near_me_uses_default_radius_with_coordinates(self):
        backend = _CapturingBackend()
        with patch("marketlift.search.service._load_backend", return_value=backend):
            search_listings(
                SearchRequest(
                    q="iphone perto de mim",
                    latitude=-23.5505,
                    longitude=-46.6333,
                )
            )
        self.assertEqual(backend.request.radius_km, 25.0)

    def test_query_radius_is_applied_with_coordinates(self):
        backend = _CapturingBackend()
        with patch("marketlift.search.service._load_backend", return_value=backend):
            search_listings(
                SearchRequest(
                    q="iphone within 20km of me",
                    latitude=-23.5505,
                    longitude=-46.6333,
                )
            )
        self.assertEqual(backend.request.radius_km, 20.0)
        self.assertEqual(backend.parsed.specification_tokens, ())

    def test_ui_radius_and_query_radius_use_stricter_bound(self):
        backend = _CapturingBackend()
        with patch("marketlift.search.service._load_backend", return_value=backend):
            search_listings(
                SearchRequest(
                    q="iphone within 20km of me",
                    latitude=-23.5505,
                    longitude=-46.6333,
                    radius_km=10,
                )
            )
        self.assertEqual(backend.request.radius_km, 10.0)

    def test_unreasonably_large_numeric_specification_is_rejected(self):
        with self.assertRaises(ValidationError):
            search_listings(
                SearchRequest(q="notebook pelo menos 999999999999999gb ram")
            )
