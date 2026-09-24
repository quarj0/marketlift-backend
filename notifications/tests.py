from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from accounts.models import AccountSettings
from notifications.services import create_notification
from notifications.tasks import deliver_notification_email

User = get_user_model()


class NotificationTests(TestCase):
    def test_create_notification_queues_email_after_commit(self):
        user = User.objects.create_user(
            email="queued@example.com", password="pass", full_name="Queued"
        )
        AccountSettings.objects.create(user=user)

        with (
            patch("notifications.tasks.enqueue_notification_email") as enqueue,
            self.captureOnCommitCallbacks(execute=True),
        ):
            item = create_notification(
                user=user,
                notification_type="message",
                title="New message",
                body="Hello",
            )

        enqueue.assert_called_once_with(str(item.id))

    def test_message_email_delivery_honors_preference(self):
        user = User.objects.create_user(
            email="preference@example.com", password="pass", full_name="Preference"
        )
        settings = AccountSettings.objects.create(user=user, email_messages=False)
        item = create_notification(
            user=user,
            notification_type="message",
            title="New message",
            body="Should not be emailed",
        )

        with patch("notifications.tasks.send_mail") as send:
            self.assertEqual(deliver_notification_email(str(item.id)), "preference-disabled")
            send.assert_not_called()

        item.refresh_from_db()
        self.assertIsNotNone(item.email_sent_at)

        settings.email_messages = True
        settings.save(update_fields=("email_messages", "updated_at"))
        second = create_notification(
            user=user,
            notification_type="message",
            title="New message",
            body="This one should be emailed",
        )
        with patch("notifications.tasks.send_mail", return_value=1) as send:
            self.assertEqual(deliver_notification_email(str(second.id)), "sent")
            send.assert_called_once()

        second.refresh_from_db()
        self.assertIsNotNone(second.email_sent_at)

    def test_mark_read(self):
        user = User.objects.create_user(
            email="n@example.com", password="pass", full_name="N"
        )
        n = create_notification(
            user=user, notification_type="listing", title="x", body="y"
        )
        self.assertFalse(n.read)
        n.mark_read()
        self.assertTrue(n.read)
