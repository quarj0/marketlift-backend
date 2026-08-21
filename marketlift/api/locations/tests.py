from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from categories.models import Category
from listings.models import Listing
from sellers.models import SellerProfile


class LocationSuggestionTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(
            email="location-seller@example.com",
            password="Secure-Location-482!",
            full_name="Location Seller",
        )
        seller = SellerProfile.objects.create(user=user, display_name="Location Seller")
        category = Category.objects.create(slug="location-test", name="Location Test")
        for district in ("Pinheiros", "Pinheiros", "Vila Madalena"):
            Listing.objects.create(
                seller=seller,
                category=category,
                title=f"Listing in {district}",
                description="Location suggestion fixture",
                state="São Paulo",
                state_code="SP",
                city="São Paulo",
                district=district,
                status=Listing.Status.PUBLISHED,
            )
        self.client = APIClient()

    def test_returns_distinct_marketplace_neighborhoods(self):
        response = self.client.get(
            "/api/v1/locations/neighborhoods/",
            {"state": "SP", "city": "São Paulo"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["suggestions"], ["Pinheiros", "Vila Madalena"])

    def test_can_filter_neighborhood_suggestions(self):
        response = self.client.get(
            "/api/v1/locations/neighborhoods/",
            {"state": "SP", "city": "São Paulo", "q": "Vila"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["suggestions"], ["Vila Madalena"])


class LocationReferenceTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_regions_and_region_filtered_states_are_available(self):
        regions = self.client.get("/api/v1/locations/regions/")
        self.assertEqual(regions.status_code, 200)
        self.assertEqual(len(regions.json()["regions"]), 5)

        states = self.client.get("/api/v1/locations/states/", {"region": "SE"})
        self.assertEqual(states.status_code, 200)
        codes = {row["code"] for row in states.json()["states"]}
        self.assertEqual(codes, {"ES", "MG", "RJ", "SP"})

    def test_invalid_state_is_rejected_by_city_catalog(self):
        response = self.client.get("/api/v1/locations/cities/", {"state": "XX"})
        self.assertEqual(response.status_code, 400)
