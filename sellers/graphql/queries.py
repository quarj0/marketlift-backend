import strawberry
from django.db.models import Q

from marketlift.graphql.auth import require_staff
from sellers.models import SellerProfile
from .mappers import admin_seller_to_type, seller_to_type
from .types import AdminSellerType, SellerType


@strawberry.type
class SellerQuery:
    @strawberry.field
    def seller(self, id: strawberry.ID) -> SellerType | None:
        try:
            seller = SellerProfile.objects.select_related("user").get(
                pk=str(id), is_suspended=False
            )
        except (SellerProfile.DoesNotExist, ValueError):
            return None
        return seller_to_type(seller)

    @strawberry.field
    def admin_sellers(
        self,
        info: strawberry.Info,
        search: str | None = None,
        suspended: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AdminSellerType]:
        require_staff(info)
        qs = SellerProfile.objects.select_related("user").all()
        if search:
            qs = qs.filter(
                Q(display_name__icontains=search)
                | Q(user__full_name__icontains=search)
                | Q(user__email__icontains=search)
            )
        if suspended is not None:
            qs = qs.filter(is_suspended=suspended)
        qs = qs[max(0, offset) : max(0, offset) + max(1, min(limit, 100))]
        return [admin_seller_to_type(seller) for seller in qs]
