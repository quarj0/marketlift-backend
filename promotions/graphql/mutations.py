import strawberry
from django.core.exceptions import ValidationError
from graphql import GraphQLError
from listings.models import Listing
from marketlift.graphql.auth import request_from_info, require_seller
from marketlift.graphql.errors import validation_error
from promotions.models import PromotionProduct
from promotions.services import activate_with_plan_credit
from .types import ListingPromotionType


@strawberry.type
class PromotionMutation:
    @strawberry.mutation
    def activate_promotion_with_plan_credit(
        self, info: strawberry.Info, listing_id: strawberry.ID, promotion_id: str
    ) -> ListingPromotionType:
        seller = require_seller(info)
        try:
            listing = Listing.objects.get(pk=str(listing_id))
            product = PromotionProduct.objects.get(code=promotion_id, active=True)
        except (Listing.DoesNotExist, PromotionProduct.DoesNotExist, ValueError) as exc:
            raise GraphQLError("Listing or promotion not found.") from exc
        try:
            item = activate_with_plan_credit(
                seller=seller,
                listing=listing,
                product=product,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(exc) from exc
        return ListingPromotionType(
            id=str(item.id),
            listing_id=str(item.listing_id),
            product_id=item.product.code,
            source=item.source,
            starts_at=item.starts_at,
            ends_at=item.ends_at,
            active=item.is_active,
        )
