import strawberry
from django.core.exceptions import ValidationError
from marketlift.graphql.auth import require_seller, require_user
from sellers.models import SellerProfile
from reviews.models import SellerReview
from .mappers import reputation_to_type, review_to_type
from .types import ReviewType, SellerReputationType


@strawberry.type
class ReviewQuery:
    @strawberry.field
    def seller_reviews(
        self, seller_id: strawberry.ID, limit: int = 20, offset: int = 0
    ) -> list[ReviewType]:
        try:
            seller = SellerProfile.objects.get(pk=str(seller_id))
        except (SellerProfile.DoesNotExist, ValueError):
            return []
        qs = SellerReview.objects.select_related(
            "seller__user", "reviewer", "listing"
        ).filter(seller=seller, hidden_at__isnull=True)
        return [
            review_to_type(x)
            for x in qs[max(0, offset) : max(0, offset) + max(1, min(limit, 100))]
        ]

    @strawberry.field
    def seller_reputation(
        self, seller_id: strawberry.ID
    ) -> SellerReputationType | None:
        try:
            seller = SellerProfile.objects.get(pk=str(seller_id))
        except (SellerProfile.DoesNotExist, ValueError):
            return None
        return reputation_to_type(seller)

    @strawberry.field
    def my_reviews(self, info: strawberry.Info) -> list[ReviewType]:
        user = require_user(info)
        return [
            review_to_type(x)
            for x in SellerReview.objects.select_related(
                "seller__user", "reviewer", "listing"
            ).filter(reviewer=user)
        ]

    @strawberry.field
    def my_seller_reviews(self, info: strawberry.Info) -> list[ReviewType]:
        seller = require_seller(info)
        return [
            review_to_type(x)
            for x in SellerReview.objects.select_related(
                "seller__user", "reviewer", "listing"
            ).filter(seller=seller, hidden_at__isnull=True)
        ]
