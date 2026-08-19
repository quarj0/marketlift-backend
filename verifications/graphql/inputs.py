from datetime import date
import strawberry


@strawberry.input
class VerificationSubmissionInput:
    cpf: str
    legal_name: str
    birth_date: date
    document_type: str | None = None
    document_front_url: str | None = None
    document_back_url: str | None = None
    selfie_url: str | None = None
