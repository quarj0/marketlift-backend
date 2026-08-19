from django.contrib.auth import get_user_model
from django.test import TestCase
from notifications.services import create_notification

User = get_user_model()


class NotificationTests(TestCase):
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
