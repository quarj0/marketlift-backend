import asyncio
import json
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from marketlift.api.views import _realtime_round_trip


class HangingChannelLayer:
    async def new_channel(self, prefix):
        return f"{prefix}test"

    async def send(self, channel_name, message):
        return None

    async def receive(self, channel_name):
        await asyncio.Event().wait()


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

    @override_settings(MARKETLIFT_DEPENDENCY_TIMEOUT_SECONDS=0.01)
    @patch("marketlift.api.views.get_channel_layer")
    @patch("marketlift.api.views.cache")
    @patch("marketlift.api.views.connection")
    def test_readiness_returns_instead_of_hanging_on_realtime(
        self,
        connection,
        cache,
        get_channel_layer,
    ):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [(1,), (True,)]
        connection.cursor.return_value.__enter__.return_value = cursor
        connection.vendor = "postgresql"
        cache.get.return_value = "ok"
        get_channel_layer.return_value = HangingChannelLayer()

        response = self.client.get("/api/v1/ready/")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["checks"]["database"], "ok")
        self.assertEqual(response.json()["checks"]["redis"], "ok")
        self.assertEqual(response.json()["checks"]["realtime"], "unavailable")


class ReadinessTimeoutTests(IsolatedAsyncioTestCase):
    async def test_realtime_round_trip_can_be_bounded(self):
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(
                _realtime_round_trip(HangingChannelLayer()),
                timeout=0.01,
            )
