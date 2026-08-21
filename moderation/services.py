from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from audit.services import record_audit_event
from listings.models import Listing
from notifications.services import create_notification
from .models import ModerationCase


def _reason(value):
    value = value.strip()
    if not value:
        raise ValidationError({"reason": "A reason is required."})
    return value


def _final_case(listing):
    try:
        case = listing.moderation_case
    except ModerationCase.DoesNotExist:
        return None
    return case if case.final else None


@transaction.atomic
def move_listing_to_review(
    *, listing, actor, reason: str, source=ModerationCase.Source.MANUAL, request=None
):
    reason = _reason(reason)
    if listing.status in {Listing.Status.REJECTED, Listing.Status.REMOVED}:
        raise ValidationError("A rejected or removed listing cannot return to review.")
    final = _final_case(listing)
    if final:
        raise ValidationError(
            f"This listing already has the final moderation decision '{final.status}'."
        )
    case, created = ModerationCase.objects.get_or_create(
        listing=listing,
        defaults={"source": source, "review_reason": reason, "opened_by": actor},
    )
    if not created:
        case.source = source
        case.review_reason = reason
        case.opened_by = case.opened_by or actor
        case.save(update_fields=("source", "review_reason", "opened_by", "updated_at"))
    listing.status = Listing.Status.UNDER_REVIEW
    listing.save(update_fields=("status", "updated_at"))
    record_audit_event(
        actor=actor,
        action="listing.moved_to_review",
        target=listing,
        target_type="listing",
        target_label=listing.title,
        metadata={"reason": reason, "source": source},
        request=request,
    )
    create_notification(
        user=listing.seller.user,
        notification_type="listing",
        title="Listing under review",
        body=f"Your listing '{listing.title}' is being reviewed.",
        href=f"/selling/listings/{listing.id}/edit",
    )
    return case


@transaction.atomic
def approve_listing_case(*, listing, actor, reason: str = "", request=None):
    if listing.status in {Listing.Status.REJECTED, Listing.Status.REMOVED}:
        raise ValidationError("A rejected or removed listing cannot be approved.")
    try:
        case = listing.moderation_case
    except ModerationCase.DoesNotExist:
        raise ValidationError(
            "Move the listing to moderation review before approving it."
        )
    if case.final:
        raise ValidationError(
            f"This moderation case is already final as '{case.status}'."
        )
    case.status = ModerationCase.Status.APPROVED
    case.decision_reason = reason.strip()
    case.decided_by = actor
    case.decided_at = timezone.now()
    case.save()
    listing.status = Listing.Status.PUBLISHED
    listing.published_at = listing.published_at or timezone.now()
    listing.save(update_fields=("status", "published_at", "updated_at"))
    record_audit_event(
        actor=actor,
        action="listing.approved",
        target=listing,
        target_type="listing",
        target_label=listing.title,
        metadata={"reason": reason.strip()},
        request=request,
    )
    create_notification(
        user=listing.seller.user,
        notification_type="listing",
        title="Listing approved",
        body=f"Your listing '{listing.title}' was approved and is live.",
        href=f"/listing/{listing.slug}",
    )
    return case


@transaction.atomic
def reject_listing_case(*, listing, actor, reason: str, request=None):
    reason = _reason(reason)
    if listing.status in {Listing.Status.REJECTED, Listing.Status.REMOVED}:
        raise ValidationError("This listing already has a final unavailable state.")
    try:
        case = listing.moderation_case
    except ModerationCase.DoesNotExist:
        raise ValidationError(
            "Move the listing to moderation review before rejecting it."
        )
    if case.final:
        raise ValidationError(
            f"This moderation case is already final as '{case.status}'."
        )
    case.status = ModerationCase.Status.REJECTED
    case.decision_reason = reason
    case.decided_by = actor
    case.decided_at = timezone.now()
    case.save()
    listing.status = Listing.Status.REJECTED
    listing.save(update_fields=("status", "updated_at"))
    record_audit_event(
        actor=actor,
        action="listing.rejected",
        target=listing,
        target_type="listing",
        target_label=listing.title,
        metadata={"reason": reason},
        request=request,
    )
    create_notification(
        user=listing.seller.user,
        notification_type="listing",
        title="Listing rejected",
        body=f"Your listing '{listing.title}' was rejected.",
        href="/selling/listings",
        data={"reason": reason},
    )
    return case


@transaction.atomic
def remove_listing(*, listing, actor, reason: str, request=None):
    reason = _reason(reason)
    if listing.status == Listing.Status.REMOVED:
        return listing
    if listing.status == Listing.Status.REJECTED:
        raise ValidationError(
            "A rejected listing is already unavailable and its final moderation decision cannot be replaced."
        )
    final_case = _final_case(listing)
    prior_status = listing.status
    listing.status = Listing.Status.REMOVED
    listing.save(update_fields=("status", "updated_at"))
    record_audit_event(
        actor=actor,
        action="listing.removed",
        target=listing,
        target_type="listing",
        target_label=listing.title,
        metadata={
            "reason": reason,
            "prior_listing_status": prior_status,
            "prior_moderation_case_id": str(final_case.id) if final_case else None,
            "prior_moderation_decision": final_case.status if final_case else None,
        },
        request=request,
    )
    create_notification(
        user=listing.seller.user,
        notification_type="listing",
        title="Listing removed",
        body=f"Your listing '{listing.title}' was removed from Marketlift.",
        href="/selling/listings",
        data={"reason": reason},
    )
    return listing
