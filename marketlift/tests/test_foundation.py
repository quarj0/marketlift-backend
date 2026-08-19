import json

from django.test import SimpleTestCase


class FoundationEndpointTests(SimpleTestCase):
    def test_rest_health(self):
        response = self.client.get("/api/v1/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_graphql_health(self):
        response = self.client.get(
            "/graphql/",
            {"query": "{ health }"},
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["data"]["health"], "ok")
