from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event


@transaction.atomic
def suspend_account(*, user, actor, reason: str, request=None):
    reason = reason.strip()
    if not reason:
        raise ValidationError({"reason": "A suspension reason is required."})
    if user.is_superuser:
        raise ValidationError(
            "A superuser account cannot be suspended through this action."
        )
    if not user.is_active and user.suspended_at:
        return user
    user.is_active = False
    user.suspended_at = timezone.now()
    user.suspension_reason = reason
    user.save(
        update_fields=("is_active", "suspended_at", "suspension_reason", "updated_at")
    )
    record_audit_event(
        actor=actor,
        action="account.suspended",
        target=user,
        target_type="user",
        target_label=user.full_name or user.email,
        metadata={"reason": reason},
        request=request,
    )
    return user


@transaction.atomic
def reactivate_account(*, user, actor, reason: str, request=None):
    reason = reason.strip()
    if not reason:
        raise ValidationError({"reason": "A reactivation reason is required."})
    if user.is_active and user.suspended_at is None:
        return user
    previous_reason = user.suspension_reason
    user.is_active = True
    user.suspended_at = None
    user.suspension_reason = ""
    user.save(
        update_fields=("is_active", "suspended_at", "suspension_reason", "updated_at")
    )
    record_audit_event(
        actor=actor,
        action="account.reactivated",
        target=user,
        target_type="user",
        target_label=user.full_name or user.email,
        metadata={"reason": reason, "previous_suspension_reason": previous_reason},
        request=request,
    )
    return user
