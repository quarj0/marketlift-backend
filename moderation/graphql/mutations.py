import strawberry
from django.core.exceptions import ValidationError
from listings.models import Listing
from listings.graphql.mappers import listing_queryset, listing_to_type
from listings.graphql.types import ListingType
from marketlift.graphql.auth import request_from_info, require_staff
from marketlift.graphql.errors import (
    finality_validation_error,
    not_found_error,
)
from moderation.services import (
    approve_listing_case,
    move_listing_to_review,
    reject_listing_case,
    remove_listing,
)
from .mappers import moderation_case_to_type
from .types import ModerationCaseType


def _listing(id):
    try:
        return Listing.objects.select_related("seller__user", "category").get(
            pk=str(id)
        )
    except (Listing.DoesNotExist, ValueError) as exc:
        raise not_found_error("Listing", code="LISTING_NOT_FOUND") from exc


@strawberry.type
class ModerationMutation:
    @strawberry.mutation
    def move_listing_to_review(
        self, info: strawberry.Info, listing_id: strawberry.ID, reason: str
    ) -> ModerationCaseType:
        actor = require_staff(info, roles={"admin", "moderator"})
        try:
            case = move_listing_to_review(
                listing=_listing(listing_id),
                actor=actor,
                reason=reason,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise finality_validation_error(
                exc,
                final_code="MODERATION_CASE_FINAL",
                default_code="MODERATION_VALIDATION_ERROR",
            ) from exc
        return moderation_case_to_type(case)

    @strawberry.mutation
    def approve_listing(
        self, info: strawberry.Info, listing_id: strawberry.ID, reason: str = ""
    ) -> ModerationCaseType:
        actor = require_staff(info, roles={"admin", "moderator"})
        try:
            case = approve_listing_case(
                listing=_listing(listing_id),
                actor=actor,
                reason=reason,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise finality_validation_error(
                exc,
                final_code="MODERATION_CASE_FINAL",
                default_code="MODERATION_VALIDATION_ERROR",
            ) from exc
        return moderation_case_to_type(case)

    @strawberry.mutation
    def reject_listing(
        self, info: strawberry.Info, listing_id: strawberry.ID, reason: str
    ) -> ModerationCaseType:
        actor = require_staff(info, roles={"admin", "moderator"})
        try:
            case = reject_listing_case(
                listing=_listing(listing_id),
                actor=actor,
                reason=reason,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise finality_validation_error(
                exc,
                final_code="MODERATION_CASE_FINAL",
                default_code="MODERATION_VALIDATION_ERROR",
            ) from exc
        return moderation_case_to_type(case)

    @strawberry.mutation
    def remove_listing(
        self, info: strawberry.Info, listing_id: strawberry.ID, reason: str
    ) -> ListingType:
        actor = require_staff(info, roles={"admin", "moderator"})
        try:
            listing = remove_listing(
                listing=_listing(listing_id),
                actor=actor,
                reason=reason,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise finality_validation_error(
                exc,
                final_code="MODERATION_CASE_FINAL",
                default_code="MODERATION_VALIDATION_ERROR",
            ) from exc
        return listing_to_type(listing_queryset().get(pk=listing.pk))
