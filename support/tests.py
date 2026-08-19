from django.test import TestCase
from accounts.models import User
from support.services import create_ticket


class SupportTests(TestCase):
    def test_create_ticket(self):
        u = User.objects.create_user(email="t@example.com", password="x", full_name="T")
        t = create_ticket(
            user=u, subject="Need help", category="account", message="Please help"
        )
        self.assertEqual(t.status, "open")
