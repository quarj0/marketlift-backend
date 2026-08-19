import strawberry
from django.db.models import Q
from marketlift.graphql.auth import require_staff, require_seller
from sellers.models import SellerProfile, SellerSettings
from .mappers import admin_seller_to_type, seller_to_type
from .types import AdminSellerType, SellerSettingsType, SellerType


@strawberry.type
class SellerQuery:
    @strawberry.field
    def seller(self, id: strawberry.ID) -> SellerType | None:
        try:
            return seller_to_type(
                SellerProfile.objects.select_related("user").get(
                    pk=str(id), is_suspended=False
                )
            )
        except (SellerProfile.DoesNotExist, ValueError):
            return None

    @strawberry.field
    def my_seller_settings(self, info: strawberry.Info) -> SellerSettingsType:
        seller = require_seller(info)
        x = SellerSettings.objects.get_or_create(user_profile=seller)[0]
        return SellerSettingsType(
            new_inquiry=x.new_inquiry,
            listing_status=x.listing_status,
            performance=x.performance,
            auto_renew=x.auto_renew,
            show_phone=x.show_phone,
            vacation=x.vacation,
        )

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
        qs = SellerProfile.objects.select_related("user")
        if search:
            qs = qs.filter(
                Q(display_name__icontains=search)
                | Q(user__full_name__icontains=search)
                | Q(user__email__icontains=search)
            )
        if suspended is not None:
            qs = qs.filter(is_suspended=suspended)
        return [
            admin_seller_to_type(x)
            for x in qs[max(0, offset) : max(0, offset) + max(1, min(limit, 100))]
        ]
