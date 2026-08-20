import strawberry
from django.core.exceptions import ValidationError

from marketlift.graphql.auth import request_from_info, require_seller, require_staff
from marketlift.graphql.errors import (
    finality_validation_error,
    not_found_error,
    validation_error,
)
from verifications.models import VerificationSubmission
from verifications.services import (
    approve_verification,
    move_to_review,
    reject_verification,
    submit_verification,
)
from .inputs import VerificationSubmissionInput
from .mappers import verification_to_type
from .types import VerificationType


def _get(id):
    try:
        return VerificationSubmission.objects.select_related(
            "seller", "seller__user"
        ).get(pk=str(id))
    except (VerificationSubmission.DoesNotExist, ValueError) as exc:
        raise not_found_error("Verification", code="VERIFICATION_NOT_FOUND") from exc


@strawberry.type
class VerificationMutation:
    @strawberry.mutation
    def submit_seller_verification(
        self, info: strawberry.Info, input: VerificationSubmissionInput
    ) -> VerificationType:
        seller = require_seller(info)
        try:
            item = submit_verification(
                seller=seller,
                cpf=input.cpf,
                legal_name=input.legal_name,
                birth_date=input.birth_date,
                document_type=input.document_type or "",
                document_front_url=input.document_front_url or "",
                document_back_url=input.document_back_url or "",
                selfie_url=input.selfie_url or "",
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(exc, code="VERIFICATION_VALIDATION_ERROR") from exc
        return verification_to_type(item)

    @strawberry.mutation
    def move_verification_to_review(
        self, info: strawberry.Info, id: strawberry.ID, note: str = ""
    ) -> VerificationType:
        actor = require_staff(info, roles={"admin", "moderator"})
        try:
            item = move_to_review(
                verification=_get(id),
                actor=actor,
                note=note,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise finality_validation_error(
                exc,
                final_code="VERIFICATION_FINAL",
                default_code="VERIFICATION_VALIDATION_ERROR",
            ) from exc
        return verification_to_type(item)

    @strawberry.mutation
    def approve_verification(
        self, info: strawberry.Info, id: strawberry.ID, note: str = ""
    ) -> VerificationType:
        actor = require_staff(info, roles={"admin", "moderator"})
        try:
            item = approve_verification(
                verification=_get(id),
                actor=actor,
                note=note,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise finality_validation_error(
                exc,
                final_code="VERIFICATION_FINAL",
                default_code="VERIFICATION_VALIDATION_ERROR",
            ) from exc
        return verification_to_type(item)

    @strawberry.mutation
    def reject_verification(
        self, info: strawberry.Info, id: strawberry.ID, note: str
    ) -> VerificationType:
        actor = require_staff(info, roles={"admin", "moderator"})
        try:
            item = reject_verification(
                verification=_get(id),
                actor=actor,
                note=note,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise finality_validation_error(
                exc,
                final_code="VERIFICATION_FINAL",
                default_code="VERIFICATION_VALIDATION_ERROR",
            ) from exc
        return verification_to_type(item)
