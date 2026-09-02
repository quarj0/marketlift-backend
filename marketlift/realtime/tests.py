from __future__ import annotations

from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TransactionTestCase, override_settings

from categories.models import Category
from listings.models import Listing
from marketlift.asgi import application
from messaging.services import start_conversation
from notifications.services import create_notification
from sellers.models import SellerProfile

User = get_user_model()

TEST_CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}


@override_settings(CHANNEL_LAYERS=TEST_CHANNEL_LAYERS)
class RealtimeWebSocketTests(TransactionTestCase):
    def setUp(self):
        self.buyer = User.objects.create_user(
            email="ws-buyer@example.com", full_name="Buyer", password="secret123"
        )
        self.seller_user = User.objects.create_user(
            email="ws-seller@example.com", full_name="Seller", password="secret123"
        )
        self.seller = SellerProfile.objects.create(
            user=self.seller_user, display_name="Seller"
        )
        self.category = Category.objects.create(
            slug="ws-test", name="WebSocket Test", active=True, pricing_mode="optional"
        )
        self.listing = Listing.objects.create(
            seller=self.seller,
            category=self.category,
            title="Realtime listing",
            description="Description",
            state="State",
            state_code="ST",
            city="City",
            status=Listing.Status.PUBLISHED,
        )
        self.conversation = start_conversation(buyer=self.buyer, listing=self.listing)
        self.notification = create_notification(
            user=self.buyer,
            notification_type="listing",
            title="Listing update",
            body="Something changed",
        )
        self.buyer_cookie = self._session_cookie(self.buyer)

    @staticmethod
    def _session_cookie(user):
        client = Client()
        client.force_login(user)
        return client.cookies[settings.SESSION_COOKIE_NAME].value

    def _communicator(self, cookie=None):
        origin = settings.MARKETLIFT_WEBSOCKET_ALLOWED_ORIGINS[0].encode()
        headers = [
            (b"host", b"localhost"),
            (b"origin", origin),
        ]
        if cookie:
            value = f"{settings.SESSION_COOKIE_NAME}={cookie}".encode()
            headers.append((b"cookie", value))
        return WebsocketCommunicator(application, "/ws/realtime/", headers=headers)

    def test_configured_marketplace_origin_is_allowed(self):
        self.assertIn(
            settings.MARKETLIFT_FRONTEND_URL.rstrip("/"),
            settings.MARKETLIFT_WEBSOCKET_ALLOWED_ORIGINS,
        )

    async def test_authenticated_socket_returns_recovery_counts(self):
        socket = self._communicator(self.buyer_cookie)
        connected, _ = await socket.connect()
        self.assertTrue(connected)
        event = await socket.receive_json_from(timeout=2)
        self.assertEqual(event["type"], "realtime.ready")
        self.assertEqual(event["data"]["unreadMessageCount"], 0)
        self.assertEqual(event["data"]["unreadNotificationCount"], 1)
        await socket.disconnect()

    async def test_anonymous_socket_is_rejected(self):
        socket = self._communicator()
        connected, code = await socket.connect()
        self.assertFalse(connected)
        self.assertEqual(code, 4401)

    async def test_message_can_be_sent_over_websocket(self):
        socket = self._communicator(self.buyer_cookie)
        connected, _ = await socket.connect()
        self.assertTrue(connected)
        await socket.receive_json_from(timeout=2)  # realtime.ready

        await socket.send_json_to(
            {
                "type": "message.send",
                "requestId": "request-1",
                "conversationId": str(self.conversation.id),
                "text": "Is this available?",
            }
        )

        events = [
            await socket.receive_json_from(timeout=2),
            await socket.receive_json_from(timeout=2),
        ]
        event_types = {event["type"] for event in events}
        self.assertEqual(event_types, {"command.ack", "message.created"})
        message_event = next(
            item for item in events if item["type"] == "message.created"
        )
        self.assertEqual(message_event["data"]["message"]["text"], "Is this available?")
        self.assertEqual(
            message_event["data"]["message"]["conversationId"],
            str(self.conversation.id),
        )
        await socket.disconnect()

    async def test_command_error_echoes_request_id(self):
        socket = self._communicator(self.buyer_cookie)
        connected, _ = await socket.connect()
        self.assertTrue(connected)
        await socket.receive_json_from(timeout=2)

        await socket.send_json_to(
            {
                "type": "message.send",
                "requestId": "invalid-message",
                "text": "Missing conversation",
            }
        )
        event = await socket.receive_json_from(timeout=2)
        self.assertEqual(event["type"], "error")
        self.assertEqual(event["data"]["requestId"], "invalid-message")
        self.assertEqual(event["data"]["action"], "message.send")
        await socket.disconnect()

    async def test_notification_read_all_is_realtime(self):
        socket = self._communicator(self.buyer_cookie)
        connected, _ = await socket.connect()
        self.assertTrue(connected)
        await socket.receive_json_from(timeout=2)

        await socket.send_json_to(
            {"type": "notification.read_all", "requestId": "read-all"}
        )
        events = [
            await socket.receive_json_from(timeout=2),
            await socket.receive_json_from(timeout=2),
        ]
        event_types = {event["type"] for event in events}
        self.assertEqual(event_types, {"command.ack", "notification.read_all"})
        read_event = next(
            item for item in events if item["type"] == "notification.read_all"
        )
        self.assertEqual(read_event["data"]["unreadNotificationCount"], 0)
        await socket.disconnect()
