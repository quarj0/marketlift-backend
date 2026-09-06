import json

from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import resolve


@override_settings(IS_PRODUCTION=True)
class ProductionGraphQLHTTPTests(SimpleTestCase):
    def test_server_rendered_queries_are_allowed_in_production(self):
        request = RequestFactory().get(
            "/graphql/", {"query": "{ health }"}, HTTP_ACCEPT="application/json"
        )
        response = resolve("/graphql/").func(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["health"], "ok")
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])

    def test_get_cannot_execute_a_mutation(self):
        request = RequestFactory().get(
            "/graphql/",
            {"query": "mutation { deactivateMyAccount }"},
            HTTP_ACCEPT="application/json",
        )
        response = resolve("/graphql/").func(request)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"mutations are not allowed when using GET", response.content)
