import strawberry
from marketlift.graphql.auth import require_staff, require_user
from support.models import SupportTicket
from .mappers import ticket_to_type
from .types import SupportTicketType


@strawberry.type
class SupportQuery:
    @strawberry.field
    def my_support_tickets(self, info: strawberry.Info) -> list[SupportTicketType]:
        u = require_user(info)
        return [
            ticket_to_type(x)
            for x in SupportTicket.objects.select_related("user", "assigned_to").filter(
                user=u
            )
        ]

    @strawberry.field
    def support_tickets(
        self, info: strawberry.Info, status: str | None = None, limit: int = 100
    ) -> list[SupportTicketType]:
        require_staff(info, roles={"admin", "support"})
        qs = SupportTicket.objects.select_related("user", "assigned_to")
        qs = qs.filter(status=status) if status else qs
        return [ticket_to_type(x, True) for x in qs[: max(1, min(limit, 200))]]

    @strawberry.field
    def support_ticket(
        self, info: strawberry.Info, id: strawberry.ID
    ) -> SupportTicketType | None:
        u = require_user(info)
        try:
            qs = SupportTicket.objects.select_related("user", "assigned_to")
            ticket = qs.get(pk=str(id))
            if not u.is_staff and ticket.user_id != u.pk:
                return None
            return ticket_to_type(ticket, u.is_staff)
        except (SupportTicket.DoesNotExist, ValueError):
            return None
