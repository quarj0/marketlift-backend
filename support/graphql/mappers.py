from .types import SupportMessageType, SupportTicketType


def message_to_type(x):
    return SupportMessageType(
        id=str(x.id),
        sender_name=(x.sender.full_name or x.sender.email) if x.sender_id else None,
        body=x.body,
        internal=x.internal,
        attachment_url=x.upload.content_url if x.upload_id else None,
        created_at=x.created_at,
    )


def ticket_to_type(x, include_internal=False):
    msgs = [
        message_to_type(m)
        for m in x.messages.select_related("sender", "upload").all()
        if include_internal or not m.internal
    ]
    return SupportTicketType(
        id=str(x.id),
        reference=x.reference,
        user_id=str(x.user_id),
        user_name=x.user.full_name or x.user.email,
        subject=x.subject,
        category=x.category,
        priority=x.priority,
        status=x.status,
        assigned_to=(
            (x.assigned_to.full_name or x.assigned_to.email)
            if x.assigned_to_id
            else None
        ),
        updated_at=x.updated_at,
        created_at=x.created_at,
        messages=msgs,
    )
