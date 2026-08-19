from listings.graphql.mappers import listing_queryset, listing_to_type
from .types import ModerationCaseType


def moderation_case_to_type(case):
    listing = listing_queryset().get(pk=case.listing_id)
    return ModerationCaseType(
        id=str(case.id),
        status=case.status,
        source=case.source,
        review_reason=case.review_reason,
        decision_reason=case.decision_reason or None,
        opened_at=case.created_at,
        decided_at=case.decided_at,
        decided_by=(
            (case.decided_by.full_name or case.decided_by.email)
            if case.decided_by
            else None
        ),
        listing=listing_to_type(listing),
    )
