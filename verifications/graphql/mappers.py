from .types import VerificationType


def verification_to_type(item):
    return VerificationType(
        id=str(item.id),
        seller_id=str(item.seller_id),
        seller_name=str(item.seller),
        cpf_masked=item.cpf_masked,
        legal_name=item.legal_name,
        birth_date=item.birth_date,
        document_type=item.document_type or None,
        document_front_url=item.document_front_url or None,
        document_back_url=item.document_back_url or None,
        selfie_url=item.selfie_url or None,
        status=item.status,
        risk_level=item.risk_level,
        risk_flags=list(item.risk_flags or []),
        automated_checks=item.automated_checks or {},
        provider_result=item.provider_result or None,
        submitted_at=item.submitted_at,
        review_started_at=item.review_started_at,
        decided_at=item.decided_at,
        decision_note=item.decision_note or None,
    )
