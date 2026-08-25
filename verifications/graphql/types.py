from datetime import date, datetime
import strawberry


@strawberry.type
class VerificationType:
    id: strawberry.ID
    seller_id: strawberry.ID
    seller_name: str
    identity_country_code: str
    identity_type: str
    identity_masked: str
    # Compatibility field for Brazil clients; null for non-Brazil markets.
    cpf_masked: str | None
    legal_name: str
    birth_date: date
    document_type: str | None
    document_front_url: str | None
    document_back_url: str | None
    selfie_url: str | None
    status: str
    risk_level: str
    risk_flags: list[str]
    automated_checks: strawberry.scalars.JSON
    provider: str | None
    provider_result: str | None
    submitted_at: datetime
    review_started_at: datetime | None
    decided_at: datetime | None
    decision_note: str | None


@strawberry.type
class VerificationQueueSummaryType:
    pending: int
    review: int
    verified_today: int
    rejected_today: int
