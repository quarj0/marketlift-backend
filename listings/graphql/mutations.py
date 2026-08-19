from decimal import Decimal
import strawberry
from django.core.exceptions import ValidationError
from graphql import GraphQLError

from categories.models import Category
from listings.models import Listing, SavedListing
from listings.services import (
    create_listing,
    delete_listing_by_seller,
    mark_listing_sold,
    pause_listing,
    publish_listing,
    record_listing_view,
    update_listing,
)
from marketlift.graphql.auth import (
    request_from_info,
    request_user,
    require_seller,
    require_user,
)
from marketlift.graphql.errors import validation_error
from .inputs import ListingInput
from .mappers import listing_queryset, listing_to_type
from .types import ListingType


def _decimal(value):
    return None if value is None else Decimal(str(value))


def _owned(info, listing_id):
    seller = require_seller(info)
    try:
        return listing_queryset().get(pk=str(listing_id), seller=seller)
    except (Listing.DoesNotExist, ValueError) as exc:
        raise GraphQLError("Listing not found.") from exc


@strawberry.type
class ListingMutation:
    @strawberry.mutation
    def create_listing(self, info: strawberry.Info, input: ListingInput) -> ListingType:
        seller = require_seller(info)
        try:
            category = Category.objects.prefetch_related("fields__options").get(
                slug=input.category_id
            )
            listing = create_listing(
                seller=seller,
                category=category,
                title=input.title,
                description=input.description,
                price=_decimal(input.price),
                condition=input.condition,
                negotiable=input.negotiable,
                state=input.state,
                state_code=input.state_code,
                city=input.city,
                district=input.district,
                attributes=dict(input.attributes or {}),
                image_urls=input.image_urls,
                image_upload_ids=input.image_upload_ids,
            )
        except Category.DoesNotExist as exc:
            raise GraphQLError("Category not found.") from exc
        except ValidationError as exc:
            raise validation_error(exc) from exc
        return listing_to_type(listing_queryset().get(pk=listing.pk))

    @strawberry.mutation
    def update_listing(
        self, info: strawberry.Info, listing_id: strawberry.ID, input: ListingInput
    ) -> ListingType:
        listing = _owned(info, listing_id)
        try:
            category = Category.objects.prefetch_related("fields__options").get(
                slug=input.category_id
            )
            listing = update_listing(
                listing=listing,
                category=category,
                title=input.title,
                description=input.description,
                price=_decimal(input.price),
                condition=input.condition,
                negotiable=input.negotiable,
                state=input.state,
                state_code=input.state_code,
                city=input.city,
                district=input.district,
                attributes=dict(input.attributes or {}),
                image_urls=input.image_urls,
                image_upload_ids=input.image_upload_ids,
            )
        except Category.DoesNotExist as exc:
            raise GraphQLError("Category not found.") from exc
        except ValidationError as exc:
            raise validation_error(exc) from exc
        return listing_to_type(listing_queryset().get(pk=listing.pk))

    @strawberry.mutation
    def publish_listing(
        self, info: strawberry.Info, listing_id: strawberry.ID
    ) -> ListingType:
        try:
            listing = publish_listing(_owned(info, listing_id))
        except ValidationError as exc:
            raise validation_error(exc) from exc
        return listing_to_type(listing_queryset().get(pk=listing.pk))

    @strawberry.mutation
    def pause_listing(
        self, info: strawberry.Info, listing_id: strawberry.ID
    ) -> ListingType:
        try:
            listing = pause_listing(_owned(info, listing_id))
        except ValidationError as exc:
            raise validation_error(exc) from exc
        return listing_to_type(listing_queryset().get(pk=listing.pk))

    @strawberry.mutation
    def mark_listing_sold(
        self, info: strawberry.Info, listing_id: strawberry.ID
    ) -> ListingType:
        try:
            listing = mark_listing_sold(_owned(info, listing_id))
        except ValidationError as exc:
            raise validation_error(exc) from exc
        return listing_to_type(listing_queryset().get(pk=listing.pk))

    @strawberry.mutation
    def delete_my_listing(
        self, info: strawberry.Info, listing_id: strawberry.ID, reason: str = ""
    ) -> bool:
        listing = _owned(info, listing_id)
        delete_listing_by_seller(
            listing=listing, reason=reason, request=request_from_info(info)
        )
        return True

    @strawberry.mutation
    def save_listing(self, info: strawberry.Info, listing_id: strawberry.ID) -> bool:
        user = require_user(info)
        try:
            listing = Listing.objects.public().get(pk=str(listing_id))
        except (Listing.DoesNotExist, ValueError) as exc:
            raise GraphQLError("Listing not found.") from exc
        SavedListing.objects.get_or_create(user=user, listing=listing)
        return True

    @strawberry.mutation
    def unsave_listing(self, info: strawberry.Info, listing_id: strawberry.ID) -> bool:
        user = require_user(info)
        SavedListing.objects.filter(user=user, listing_id=str(listing_id)).delete()
        return True

    @strawberry.mutation
    def record_listing_view(
        self, info: strawberry.Info, listing_id: strawberry.ID
    ) -> bool:
        try:
            listing = Listing.objects.public().get(pk=str(listing_id))
        except (Listing.DoesNotExist, ValueError) as exc:
            raise GraphQLError("Listing not found.") from exc
        user = request_user(info)
        return record_listing_view(
            listing=listing, user=user if user and user.is_authenticated else None
        )


# recordListingView is intentionally safe for authenticated users; anonymous view counting
# can be wired through the public HTTP edge later without exposing write ownership.
