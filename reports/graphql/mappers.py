from .types import ReportType


def report_to_type(r):
    target_id = r.listing_id or r.seller_id or r.user_target_id or ""
    return ReportType(
        id=str(r.id),
        reference=r.reference,
        target_type=r.target_type,
        target_id=str(target_id),
        target_label=r.target_label,
        reason=r.reason,
        statement=r.statement,
        priority=r.priority,
        status=r.status,
        reporter_name=(
            (r.reporter.full_name or r.reporter.email) if r.reporter else None
        ),
        assigned_to=(
            (r.assigned_to.full_name or r.assigned_to.email) if r.assigned_to else None
        ),
        internal_note=r.internal_note or None,
        decision_reason=r.decision_reason or None,
        created_at=r.created_at,
        decided_at=r.decided_at,
    )
