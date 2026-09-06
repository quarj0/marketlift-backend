import strawberry
from django.db.models import Prefetch
from marketlift.graphql.auth import require_staff, require_user
from support.models import SupportTicket, SupportMessage
from .mappers import ticket_to_type
from .types import SupportTicketType


def ticket_queryset(*, internal=False, offset=0, limit=50):
    messages = SupportMessage.objects.select_related("sender", "upload")
    if not internal:
        messages = messages.filter(internal=False)
    start = max(0, offset)
    size = max(1, min(limit, 100))
    return SupportTicket.objects.select_related("user", "assigned_to").prefetch_related(
        Prefetch(
            "messages",
            queryset=messages.order_by("-created_at", "-id")[start : start + size + 1],
            to_attr="_page_messages",
        )
    )


@strawberry.type
class SupportQuery:
    @strawberry.field
    def my_support_tickets(
        self, info: strawberry.Info, limit: int = 50, offset: int = 0
    ) -> list[SupportTicketType]:
        u = require_user(info)
        return [
            ticket_to_type(x)
            for x in ticket_queryset()
            .filter(user=u)
            .order_by("-updated_at", "-id")[
                max(0, offset) : max(0, offset) + max(1, min(limit, 100))
            ]
        ]

    @strawberry.field
    def support_tickets(
        self,
        info: strawberry.Info,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SupportTicketType]:
        require_staff(info, roles={"admin", "support"})
        qs = ticket_queryset(internal=True)
        qs = qs.filter(status=status) if status else qs
        start = max(0, offset)
        return [
            ticket_to_type(x, True)
            for x in qs.order_by("-updated_at", "-id")[
                start : start + max(1, min(limit, 200))
            ]
        ]

    @strawberry.field
    def support_ticket(
        self,
        info: strawberry.Info,
        id: strawberry.ID,
        message_offset: int = 0,
        message_limit: int = 50,
    ) -> SupportTicketType | None:
        u = require_user(info)
        if u.is_staff:
            require_staff(info, roles={"admin", "support"})
        try:
            qs = ticket_queryset(
                internal=u.is_staff, offset=message_offset, limit=message_limit
            )
            ticket = qs.get(pk=str(id))
            if not u.is_staff and ticket.user_id != u.pk:
                return None
            return ticket_to_type(ticket, u.is_staff, message_limit=message_limit)
        except (SupportTicket.DoesNotExist, ValueError):
            return None
