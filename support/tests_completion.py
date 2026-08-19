from django.test import TestCase
from accounts.models import User
from support.models import SupportTicket
from support.services import update_ticket_workflow


class SupportWorkflowCompletionTests(TestCase):
    def test_staff_can_assign_prioritize_and_resolve_ticket(self):
        user = User.objects.create_user(
            email="customer@example.com",
            password="Example-Secure-482!",
            full_name="Customer",
        )
        staff = User.objects.create_user(
            email="support@example.com",
            password="Example-Secure-482!",
            full_name="Support",
            is_staff=True,
            admin_role=User.AdminRole.SUPPORT,
        )
        ticket = SupportTicket.objects.create(user=user, subject="Help")
        ticket = update_ticket_workflow(
            staff=staff,
            ticket=ticket,
            status=SupportTicket.Status.RESOLVED,
            priority=SupportTicket.Priority.HIGH,
            assigned_to=staff,
        )
        self.assertEqual(ticket.status, SupportTicket.Status.RESOLVED)
        self.assertEqual(ticket.priority, SupportTicket.Priority.HIGH)
        self.assertEqual(ticket.assigned_to, staff)
        self.assertIsNotNone(ticket.resolved_at)
