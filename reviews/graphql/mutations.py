import strawberry
from django.core.exceptions import PermissionDenied, ValidationError
from graphql import GraphQLError
from listings.models import Listing
from marketlift.graphql.auth import require_seller, require_user
from marketlift.graphql.errors import validation_error
from reviews.models import SellerReview
from reviews.services import create_review, delete_own_review, reply_to_review
from sellers.models import SellerProfile
from .inputs import CreateReviewInput
from .mappers import review_to_type
from .types import ReviewType


@strawberry.type
class ReviewMutation:
    @strawberry.mutation
    def create_review(
        self, info: strawberry.Info, input: CreateReviewInput
    ) -> ReviewType:
        user = require_user(info)
        try:
            seller = SellerProfile.objects.get(pk=str(input.seller_id))
            listing = (
                Listing.objects.get(pk=str(input.listing_id))
                if input.listing_id
                else None
            )
            return review_to_type(
                create_review(
                    reviewer=user,
                    seller=seller,
                    rating=input.rating,
                    comment=input.comment,
                    listing=listing,
                    request=getattr(info.context, "request", info.context),
                )
            )
        except (SellerProfile.DoesNotExist, Listing.DoesNotExist):
            raise GraphQLError("Seller or listing not found.")
        except (ValidationError, PermissionDenied) as exc:
            raise (
                validation_error(exc)
                if isinstance(exc, ValidationError)
                else GraphQLError(str(exc))
            )

    @strawberry.mutation
    def reply_to_review(
        self, info: strawberry.Info, review_id: strawberry.ID, reply: str
    ) -> ReviewType:
        seller = require_seller(info)
        try:
            review = SellerReview.objects.get(pk=str(review_id))
            return review_to_type(
                reply_to_review(
                    seller=seller,
                    review=review,
                    reply=reply,
                    request=getattr(info.context, "request", info.context),
                )
            )
        except SellerReview.DoesNotExist:
            raise GraphQLError("Review not found.")
        except (ValidationError, PermissionDenied) as exc:
            raise (
                validation_error(exc)
                if isinstance(exc, ValidationError)
                else GraphQLError(str(exc))
            )

    @strawberry.mutation
    def delete_my_review(self, info: strawberry.Info, review_id: strawberry.ID) -> bool:
        user = require_user(info)
        try:
            review = SellerReview.objects.get(pk=str(review_id))
            return delete_own_review(
                reviewer=user,
                review=review,
                request=getattr(info.context, "request", info.context),
            )
        except SellerReview.DoesNotExist:
            return True
        except PermissionDenied as exc:
            raise GraphQLError(str(exc))
