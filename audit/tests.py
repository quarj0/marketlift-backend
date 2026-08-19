from django.contrib.auth import get_user_model
from django.test import TestCase
from audit.services import record_audit_event

User = get_user_model()


class AuditTests(TestCase):
    def test_event_records_actor_snapshot(self):
        u = User.objects.create_user(
            email="a@example.com", password="pass", full_name="Audit User"
        )
        event = record_audit_event(
            actor=u,
            action="test.action",
            target=u,
            target_type="user",
            target_label="Audit User",
        )
        self.assertEqual(event.actor_email, "a@example.com")
