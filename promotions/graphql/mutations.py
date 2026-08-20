import strawberry
from django.core.exceptions import ValidationError
from listings.models import Listing
from marketlift.graphql.auth import request_from_info, require_seller
from marketlift.graphql.errors import not_found_error, validation_error
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
            raise not_found_error(
                "Listing or promotion", code="PROMOTION_TARGET_NOT_FOUND"
            ) from exc
        try:
            item = activate_with_plan_credit(
                seller=seller,
                listing=listing,
                product=product,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(exc, code="PROMOTION_VALIDATION_ERROR") from exc
        return ListingPromotionType(
            id=str(item.id),
            listing_id=str(item.listing_id),
            product_id=item.product.code,
            source=item.source,
            starts_at=item.starts_at,
            ends_at=item.ends_at,
            active=item.is_active,
        )
