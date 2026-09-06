from types import SimpleNamespace

from django.test import TestCase
from accounts.models import User
from support.models import SupportTicket, SupportMessage
from support.graphql.queries import SupportQuery
from marketlift.graphql.schema import schema


class SupportAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = User.objects.create_user(email="customer@example.invalid")
        cls.ticket = SupportTicket.objects.create(user=cls.customer, subject="Question")
        SupportMessage.objects.create(
            ticket=cls.ticket, sender=cls.customer, body="Private", internal=True
        )

    def test_unrelated_staff_role_cannot_read_ticket(self):
        staff = User.objects.create_user(
            email="staff@example.invalid", is_staff=True, admin_role="finance"
        )
        result = schema.execute_sync(
            "query($id:ID!){supportTicket(id:$id){messages{body internal}}}",
            variable_values={"id": str(self.ticket.id)},
            context_value=SimpleNamespace(user=staff),
        )
        self.assertTrue(result.errors)
        self.assertNotIn("Private", str(result.data))

    def test_customer_never_receives_internal_notes(self):
        info = SimpleNamespace(context=SimpleNamespace(user=self.customer))
        self.assertEqual(
            SupportQuery().support_ticket(info, self.ticket.id).messages, []
        )

    def test_ticket_page_query_count_is_bounded(self):
        for i in range(10):
            ticket = SupportTicket.objects.create(user=self.customer, subject=str(i))
            SupportMessage.objects.create(
                ticket=ticket, sender=self.customer, body="Hello"
            )
        with self.assertNumQueries(2):
            rows = SupportQuery().my_support_tickets(
                SimpleNamespace(context=SimpleNamespace(user=self.customer))
            )
        self.assertEqual(len(rows), 11)
