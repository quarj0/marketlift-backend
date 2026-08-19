from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from audit.services import record_audit_event
from notifications.services import create_notification
from uploads.models import UploadAsset
from uploads.services import claim_upload
from .models import SupportMessage, SupportTicket


def _body(value):
    value = (value or "").strip()
    if len(value) < 2:
        raise ValidationError({"message": "Message cannot be empty."})
    return value


@transaction.atomic
def create_ticket(*, user, subject, category, message, upload=None, request=None):
    subject = (subject or "").strip()
    if len(subject) < 3:
        raise ValidationError({"subject": "Subject is too short."})
    ticket = SupportTicket.objects.create(
        user=user,
        subject=subject[:180],
        category=(
            category
            if category in SupportTicket.Category.values
            else SupportTicket.Category.OTHER
        ),
        last_customer_message_at=timezone.now(),
    )
    if upload:
        upload = claim_upload(
            asset=upload, user=user, purpose=UploadAsset.Purpose.SUPPORT_ATTACHMENT
        )
    SupportMessage.objects.create(
        ticket=ticket, sender=user, body=_body(message), upload=upload
    )
    record_audit_event(
        actor=user,
        action="support.ticket_created",
        target=ticket,
        target_type="support_ticket",
        target_label=ticket.reference,
        request=request,
    )
    return ticket


@transaction.atomic
def add_customer_message(*, user, ticket, message, upload=None):
    ticket = SupportTicket.objects.select_for_update().get(pk=ticket.pk)
    if ticket.user_id != user.pk:
        raise PermissionDenied("This ticket belongs to another account.")
    if ticket.status == SupportTicket.Status.CLOSED:
        raise ValidationError("This ticket is closed.")
    if upload:
        upload = claim_upload(
            asset=upload, user=user, purpose=UploadAsset.Purpose.SUPPORT_ATTACHMENT
        )
    row = SupportMessage.objects.create(
        ticket=ticket, sender=user, body=_body(message), upload=upload
    )
    ticket.last_customer_message_at = row.created_at
    if ticket.status == SupportTicket.Status.RESOLVED:
        ticket.status = SupportTicket.Status.OPEN
        ticket.resolved_at = None
    ticket.save(
        update_fields=(
            "last_customer_message_at",
            "status",
            "resolved_at",
            "updated_at",
        )
    )
    return row


@transaction.atomic
def staff_reply(*, staff, ticket, message, internal=False, status=None, request=None):
    if not staff.is_staff:
        raise PermissionDenied("Admin permission required.")
    ticket = SupportTicket.objects.select_for_update().get(pk=ticket.pk)
    row = SupportMessage.objects.create(
        ticket=ticket, sender=staff, body=_body(message), internal=internal
    )
    ticket.last_staff_message_at = row.created_at
    ticket.assigned_to = ticket.assigned_to or staff
    if status in SupportTicket.Status.values:
        ticket.status = status
    elif ticket.status == SupportTicket.Status.OPEN:
        ticket.status = SupportTicket.Status.REVIEW
    if ticket.status == SupportTicket.Status.RESOLVED:
        ticket.resolved_at = timezone.now()
    if ticket.status == SupportTicket.Status.CLOSED:
        ticket.closed_at = timezone.now()
    ticket.save(
        update_fields=(
            "last_staff_message_at",
            "assigned_to",
            "status",
            "resolved_at",
            "closed_at",
            "updated_at",
        )
    )
    if not internal:
        create_notification(
            user=ticket.user,
            notification_type="support",
            title=f"Support replied to {ticket.reference}",
            body=row.body[:160],
            href="/account/support",
            data={"ticketId": str(ticket.id)},
        )
    record_audit_event(
        actor=staff,
        action="support.replied" if not internal else "support.internal_note",
        target=ticket,
        target_type="support_ticket",
        target_label=ticket.reference,
        request=request,
    )
    return row


@transaction.atomic
def update_ticket_workflow(
    *, staff, ticket, status=None, priority=None, assigned_to=None, request=None
):
    if not staff.is_staff:
        raise PermissionDenied("Admin permission required.")
    ticket = SupportTicket.objects.select_for_update().get(pk=ticket.pk)
    changed = []
    if status is not None:
        if status not in SupportTicket.Status.values:
            raise ValidationError({"status": "Invalid support ticket status."})
        ticket.status = status
        changed.append("status")
        if status == SupportTicket.Status.RESOLVED:
            ticket.resolved_at = timezone.now()
            ticket.closed_at = None
            changed += ["resolved_at", "closed_at"]
        elif status == SupportTicket.Status.CLOSED:
            ticket.closed_at = timezone.now()
            changed.append("closed_at")
        else:
            ticket.resolved_at = None
            ticket.closed_at = None
            changed += ["resolved_at", "closed_at"]
    if priority is not None:
        if priority not in SupportTicket.Priority.values:
            raise ValidationError({"priority": "Invalid support ticket priority."})
        ticket.priority = priority
        changed.append("priority")
    if assigned_to is not None:
        if not assigned_to.is_staff or not assigned_to.is_active:
            raise ValidationError(
                {"assignedTo": "Ticket assignee must be an active administrator."}
            )
        ticket.assigned_to = assigned_to
        changed.append("assigned_to")
    if changed:
        ticket.save(update_fields=tuple(dict.fromkeys(changed + ["updated_at"])))
    record_audit_event(
        actor=staff,
        action="support.workflow_updated",
        target=ticket,
        target_type="support_ticket",
        target_label=ticket.reference,
        metadata={
            "status": ticket.status,
            "priority": ticket.priority,
            "assignedTo": str(ticket.assigned_to_id) if ticket.assigned_to_id else None,
        },
        request=request,
    )
    return ticket
