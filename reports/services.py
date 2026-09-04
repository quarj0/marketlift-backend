from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from audit.services import record_audit_event
from listings.models import Listing
from messaging.models import Message
from notifications.services import create_notification
from sellers.models import SellerProfile
from .models import Report

User = get_user_model()


def _required(v, msg):
    v = v.strip()
    if not v:
        raise ValidationError(msg)
    return v


def _target(target_type, target_id):
    try:
        if target_type == Report.TargetType.LISTING:
            obj = Listing.objects.select_related("seller__user").get(pk=str(target_id))
            return {"listing": obj, "target_label_snapshot": obj.title}
        if target_type == Report.TargetType.SELLER:
            obj = SellerProfile.objects.select_related("user").get(pk=str(target_id))
            return {"seller": obj, "target_label_snapshot": str(obj)}
        if target_type == Report.TargetType.USER:
            obj = User.objects.get(pk=str(target_id))
            return {
                "user_target": obj,
                "target_label_snapshot": obj.full_name or obj.email,
            }
        if target_type == Report.TargetType.MESSAGE:
            obj = Message.objects.select_related(
                "sender", "conversation__buyer", "conversation__seller__user"
            ).get(pk=str(target_id))
            preview = (obj.text or "Image message")[:120]
            return {"message": obj, "target_label_snapshot": f"Message: {preview}"}
    except (
        Listing.DoesNotExist,
        SellerProfile.DoesNotExist,
        User.DoesNotExist,
        Message.DoesNotExist,
        ValueError,
    ) as exc:
        raise ValidationError("Report target not found.") from exc
    raise ValidationError("Invalid report target type.")


@transaction.atomic
def create_report(
    *,
    reporter,
    target_type,
    target_id,
    reason,
    statement,
    priority=Report.Priority.MEDIUM,
):
    if reason not in Report.Reason.values:
        raise ValidationError("Invalid report reason.")
    if priority not in Report.Priority.values:
        raise ValidationError("Invalid report priority.")
    data = _target(target_type, target_id)
    if data.get("user_target") and data["user_target"].pk == reporter.pk:
        raise ValidationError("You cannot report your own account.")
    if data.get("seller") and data["seller"].user_id == reporter.pk:
        raise ValidationError("You cannot report your own seller profile.")
    if data.get("listing") and data["listing"].seller.user_id == reporter.pk:
        raise ValidationError("You cannot report your own listing.")
    if data.get("message"):
        message = data["message"]
        if not message.conversation.includes_user(reporter):
            raise ValidationError(
                "You can only report messages from your own conversations."
            )
        if message.sender_id == reporter.pk:
            raise ValidationError("You cannot report your own message.")
    statement = statement.strip() or Report.Reason(reason).label
    report = Report(
        reporter=reporter,
        target_type=target_type,
        reason=reason,
        statement=statement,
        priority=priority,
        **data,
    )
    report.full_clean()
    report.save()
    return report


@transaction.atomic
def move_report_to_review(*, report, actor, note: str = "", request=None):
    if report.final:
        raise ValidationError("A final report cannot return to review.")
    report.status = Report.Status.REVIEW
    report.assigned_to = actor
    if note.strip():
        report.internal_note = note.strip()
    report.save(update_fields=("status", "assigned_to", "internal_note", "updated_at"))
    record_audit_event(
        actor=actor,
        action="report.moved_to_review",
        target=report,
        target_type="report",
        target_label=report.reference,
        metadata={"note": note.strip()},
        request=request,
    )
    return report


def _decide(*, report, actor, status, reason, request=None):
    if report.final:
        raise ValidationError(
            f"This report already has the final decision '{report.status}'."
        )
    reason = _required(reason, "A decision reason is required.")
    report.status = status
    report.decision_reason = reason
    report.decided_by = actor
    report.decided_at = timezone.now()
    report.assigned_to = actor
    report.save()
    action = (
        "report.resolved" if status == Report.Status.RESOLVED else "report.dismissed"
    )
    record_audit_event(
        actor=actor,
        action=action,
        target=report,
        target_type="report",
        target_label=report.reference,
        metadata={"reason": reason},
        request=request,
    )
    if report.reporter_id:
        create_notification(
            user=report.reporter,
            notification_type="report",
            title="Report updated",
            body=f"Your report {report.reference} has been {report.get_status_display().lower()}.",
            href="/account/reports",
            data={"reportId": str(report.id), "status": status},
        )
    return report


@transaction.atomic
def resolve_report(*, report, actor, reason, request=None):
    return _decide(
        report=report,
        actor=actor,
        status=Report.Status.RESOLVED,
        reason=reason,
        request=request,
    )


@transaction.atomic
def dismiss_report(*, report, actor, reason, request=None):
    return _decide(
        report=report,
        actor=actor,
        status=Report.Status.DISMISSED,
        reason=reason,
        request=request,
    )


@transaction.atomic
def save_internal_note(*, report, actor, note, request=None):
    if report.final:
        raise ValidationError("A final report cannot be edited.")
    report.internal_note = _required(note, "An internal note is required.")
    report.save(update_fields=("internal_note", "updated_at"))
    record_audit_event(
        actor=actor,
        action="report.note_saved",
        target=report,
        target_type="report",
        target_label=report.reference,
        request=request,
    )
    return report
