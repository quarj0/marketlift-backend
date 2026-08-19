from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from notifications.services import create_notification


@transaction.atomic
def suspend_seller(*, seller, actor, reason: str, request=None):
    reason = reason.strip()
    if not reason:
        raise ValidationError({"reason": "A suspension reason is required."})
    if seller.is_suspended:
        return seller
    seller.is_suspended = True
    seller.suspended_at = timezone.now()
    seller.suspension_reason = reason
    seller.save(
        update_fields=(
            "is_suspended",
            "suspended_at",
            "suspension_reason",
            "updated_at",
        )
    )
    record_audit_event(
        actor=actor,
        action="seller.suspended",
        target=seller,
        target_type="seller",
        target_label=str(seller),
        metadata={"reason": reason},
        request=request,
    )
    create_notification(
        user=seller.user,
        notification_type="seller",
        title="Selling access suspended",
        body="Your selling access has been suspended. Review your account for details.",
        href="/selling/settings",
        data={"reason": reason},
    )
    return seller


@transaction.atomic
def restore_seller(*, seller, actor, reason: str, request=None):
    reason = reason.strip()
    if not reason:
        raise ValidationError({"reason": "A restoration reason is required."})
    if not seller.is_suspended:
        return seller
    previous_reason = seller.suspension_reason
    seller.is_suspended = False
    seller.suspended_at = None
    seller.suspension_reason = ""
    seller.save(
        update_fields=(
            "is_suspended",
            "suspended_at",
            "suspension_reason",
            "updated_at",
        )
    )
    record_audit_event(
        actor=actor,
        action="seller.restored",
        target=seller,
        target_type="seller",
        target_label=str(seller),
        metadata={"reason": reason, "previous_suspension_reason": previous_reason},
        request=request,
    )
    create_notification(
        user=seller.user,
        notification_type="seller",
        title="Selling access restored",
        body="Your selling access has been restored.",
        href="/selling/listings",
    )
    return seller
