import base64
import os
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import AccountSettings
from notifications.models import Notification, WebPushDelivery, WebPushSubscription
from notifications.services import (
    register_web_push_subscription,
    unregister_web_push_subscription,
)
from notifications.tasks import deliver_web_push_delivery, fanout_web_push
from notifications.web_push import (
    WebPushHTTPError,
    send_web_push,
    validate_subscription_endpoint,
)

User = get_user_model()


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _subscription_keys():
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return _b64url(public), _b64url(os.urandom(16))


def _vapid_private_key():
    key = ec.generate_private_key(ec.SECP256R1())
    return _b64url(key.private_numbers().private_value.to_bytes(32, "big"))


class WebPushTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="push@example.com",
            full_name="Push User",
            password="secret123",
        )
        self.settings = AccountSettings.objects.create(user=self.user)
        self.p256dh, self.auth = _subscription_keys()
        self.endpoint = "https://fcm.googleapis.com/fcm/send/test-subscription"

    def test_register_and_unregister_subscription(self):
        subscription = register_web_push_subscription(
            user=self.user,
            endpoint=self.endpoint,
            p256dh=self.p256dh,
            auth=self.auth,
            user_agent="Marketlift test",
        )
        self.assertTrue(subscription.active)
        self.assertEqual(subscription.user, self.user)
        self.assertEqual(subscription.user_agent, "Marketlift test")

        self.assertTrue(
            unregister_web_push_subscription(user=self.user, endpoint=self.endpoint)
        )
        subscription.refresh_from_db()
        self.assertFalse(subscription.active)

    def test_endpoint_validation_blocks_arbitrary_hosts(self):
        with self.assertRaisesMessage(ValueError, "Unsupported push service"):
            validate_subscription_endpoint("https://example.com/internal-callback")

    def test_fanout_honors_message_push_preference(self):
        register_web_push_subscription(
            user=self.user,
            endpoint=self.endpoint,
            p256dh=self.p256dh,
            auth=self.auth,
        )
        item = Notification.objects.create(
            user=self.user,
            notification_type="message",
            title="New message",
            body="Hello",
            href="/messages/123",
        )

        with patch.dict(
            os.environ,
            {"MARKETLIFT_VAPID_PRIVATE_KEY": _vapid_private_key()},
            clear=False,
        ), patch("notifications.tasks.deliver_web_push_delivery.delay") as delay:
            self.assertEqual(fanout_web_push(str(item.id)), 1)
            delay.assert_called_once()

        self.settings.push_messages = False
        self.settings.save(update_fields=("push_messages", "updated_at"))
        second = Notification.objects.create(
            user=self.user,
            notification_type="message",
            title="Another message",
            body="No push",
        )
        with patch.dict(
            os.environ,
            {"MARKETLIFT_VAPID_PRIVATE_KEY": _vapid_private_key()},
            clear=False,
        ), patch("notifications.tasks.deliver_web_push_delivery.delay") as delay:
            self.assertEqual(fanout_web_push(str(second.id)), 0)
            delay.assert_not_called()

    def test_send_web_push_uses_vapid_and_aes128gcm(self):
        subscription = register_web_push_subscription(
            user=self.user,
            endpoint=self.endpoint,
            p256dh=self.p256dh,
            auth=self.auth,
        )
        item = Notification.objects.create(
            user=self.user,
            notification_type="listing",
            title="Listing update",
            body="Your listing is live.",
            href="/selling/listings",
        )
        response = type("Response", (), {"status_code": 201, "text": ""})()

        with patch.dict(
            os.environ,
            {
                "MARKETLIFT_VAPID_PRIVATE_KEY": _vapid_private_key(),
                "MARKETLIFT_VAPID_SUBJECT": "mailto:support@marketlift.com.br",
            },
            clear=False,
        ), patch("notifications.web_push.httpx.post", return_value=response) as post:
            send_web_push(subscription=subscription, notification=item)

        _, kwargs = post.call_args
        self.assertEqual(kwargs["headers"]["Content-Encoding"], "aes128gcm")
        self.assertTrue(kwargs["headers"]["Authorization"].startswith("vapid t="))
        self.assertGreater(len(kwargs["content"]), 100)

    def test_gone_subscription_is_disabled(self):
        subscription = register_web_push_subscription(
            user=self.user,
            endpoint=self.endpoint,
            p256dh=self.p256dh,
            auth=self.auth,
        )
        item = Notification.objects.create(
            user=self.user,
            notification_type="message",
            title="New message",
            body="Hello",
        )
        delivery = WebPushDelivery.objects.create(
            notification=item,
            subscription=subscription,
        )
        with patch(
            "notifications.tasks.send_web_push",
            side_effect=WebPushHTTPError(
                410,
                "gone",
                permanent_subscription_failure=True,
            ),
        ):
            self.assertEqual(deliver_web_push_delivery(str(delivery.id)), "subscription-gone")

        subscription.refresh_from_db()
        self.assertIsNotNone(subscription.disabled_at)
