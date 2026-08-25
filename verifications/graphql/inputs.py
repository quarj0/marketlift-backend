from datetime import date
import strawberry


@strawberry.input
class VerificationSubmissionInput:
    legal_name: str
    birth_date: date
    identity_number: str | None = None
    identity_type: str | None = None
    country_code: str | None = None
    # Compatibility input for the original Brazil client. New clients should use
    # identityNumber and let the market profile tell them what document label to show.
    cpf: str | None = None
    document_type: str | None = None
    document_front_url: str | None = None
    document_back_url: str | None = None
    selfie_url: str | None = None
