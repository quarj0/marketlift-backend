from django.test import SimpleTestCase
from django.urls import resolve

from marketlift.api.views import health, readiness


class ApiRoutingTests(SimpleTestCase):
    def test_health_route_uses_function_view(self):
        match = resolve("/api/v1/health/")
        self.assertIs(match.func, health)

    def test_readiness_route_uses_function_view(self):
        match = resolve("/api/v1/ready/")
        self.assertIs(match.func, readiness)
