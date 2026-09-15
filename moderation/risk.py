from __future__ import annotations

from django.db.models import Q

from listings.models import Listing
from platform_settings.models import PlatformConfiguration
from reports.models import Report

from .models import ModerationCase
from .services import move_listing_to_review

# A single marketplace user must not be able to remove a listing by repeatedly
# reporting it. Each distinct reporter contributes at most one server-defined
# weight, using the most serious active report they have filed for the listing.
_REASON_WEIGHTS = {
    Report.Reason.FRAUD: 35,
    Report.Reason.FAKE_LISTING: 35,
    Report.Reason.PROHIBITED: 35,
    Report.Reason.SAFETY: 35,
    Report.Reason.OFFENSIVE: 25,
    Report.Reason.INCORRECT_INFO: 20,
    Report.Reason.DUPLICATE: 15,
    Report.Reason.UNAVAILABLE: 10,
    Report.Reason.ACCOUNT: 10,
    Report.Reason.PAYMENT: 10,
    Report.Reason.MODERATION: 10,
    Report.Reason.TECHNICAL: 5,
    Report.Reason.OTHER: 10,
}


def listing_report_risk_score(*, listing_id) -> int:
    """Return a bounded, server-authoritative report risk score for a listing."""

    per_reporter: dict[str, int] = {}
    reports = Report.objects.filter(
        listing_id=listing_id,
        status__in=(Report.Status.OPEN, Report.Status.REVIEW),
    ).filter(Q(reporter_id__isnull=False))
    for reporter_id, reason in reports.values_list("reporter_id", "reason"):
        key = str(reporter_id)
        weight = _REASON_WEIGHTS.get(reason, 10)
        per_reporter[key] = max(per_reporter.get(key, 0), weight)
    return min(100, sum(per_reporter.values()))


def evaluate_listing_report_risk(*, listing_id) -> int:
    """Move a published listing to moderation when its configured risk is met.

    This intentionally uses report reason + distinct reporter corroboration, not
    the client-submitted report priority, so users cannot select a "high" value
    and force an immediate takedown themselves.
    """

    config = PlatformConfiguration.load()
    if not config.automated_listing_flagging:
        return 0

    try:
        listing = Listing.objects.select_related("seller__user", "category").get(
            pk=listing_id
        )
    except (Listing.DoesNotExist, ValueError):
        return 0

    score = listing_report_risk_score(listing_id=listing.pk)
    if listing.status != Listing.Status.PUBLISHED:
        return score
    if score < config.high_risk_threshold:
        return score

    try:
        moderation_case = listing.moderation_case
    except ModerationCase.DoesNotExist:
        moderation_case = None
    if moderation_case is not None and moderation_case.final:
        return score

    move_listing_to_review(
        listing=listing,
        actor=None,
        reason=(
            f"Automated marketplace risk score {score} reached the configured "
            f"review threshold of {config.high_risk_threshold}."
        ),
        source=ModerationCase.Source.RISK,
    )
    return score
