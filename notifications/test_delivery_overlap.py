from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.db import connections
from django.test import TransactionTestCase

from accounts.models import User
from notifications.models import Notification
from notifications.tasks import deliver_pending_notification_emails


class NotificationOverlapTests(TransactionTestCase):
    def test_two_workers_do_not_send_the_same_pending_notification(self):
        user = User.objects.create_user(email="notification-overlap@example.invalid")
        notification = Notification.objects.create(
            user=user, notification_type="message", title="New message", body="Hello"
        )
        sending = Event()
        release = Event()

        def send(*args, **kwargs):
            sending.set()
            if not release.wait(timeout=10):
                raise TimeoutError("Test did not release the mail send")
            return 1

        def worker():
            try:
                return deliver_pending_notification_emails()
            finally:
                connections.close_all()

        with patch("notifications.tasks.send_mail", side_effect=send) as mail:
            with ThreadPoolExecutor(max_workers=1) as executor:
                first = executor.submit(worker)
                try:
                    self.assertTrue(sending.wait(timeout=5))
                    self.assertEqual(deliver_pending_notification_emails(), 0)
                finally:
                    release.set()
                self.assertEqual(first.result(timeout=5), 1)
            self.assertEqual(mail.call_count, 1)
        notification.refresh_from_db()
        self.assertEqual(notification.delivery_attempts, 1)
        self.assertIsNotNone(notification.email_sent_at)
