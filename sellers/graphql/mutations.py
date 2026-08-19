import strawberry
from django.core.exceptions import ValidationError
from graphql import GraphQLError

from marketlift.graphql.auth import request_from_info, require_staff, require_user
from marketlift.graphql.errors import validation_error
from sellers.models import SellerProfile
from sellers.services import restore_seller, suspend_seller
from .mappers import admin_seller_to_type, seller_to_type
from .types import AdminSellerType, SellerType


@strawberry.type
class SellerMutation:
    @strawberry.mutation
    def activate_selling(
        self,
        info: strawberry.Info,
        seller_type: str = "individual",
        display_name: str = "",
    ) -> SellerType:
        user = require_user(info)
        if seller_type not in SellerProfile.SellerType.values:
            raise GraphQLError("Invalid seller type.")
        seller, created = SellerProfile.objects.get_or_create(
            user=user,
            defaults={"seller_type": seller_type, "display_name": display_name.strip()},
        )
        if not created:
            seller.seller_type = seller_type
            if display_name.strip():
                seller.display_name = display_name.strip()
            seller.save(update_fields=("seller_type", "display_name", "updated_at"))
        return seller_to_type(seller)

    @strawberry.mutation
    def suspend_seller(
        self, info: strawberry.Info, seller_id: strawberry.ID, reason: str
    ) -> AdminSellerType:
        actor = require_staff(info)
        try:
            seller = SellerProfile.objects.select_related("user").get(pk=str(seller_id))
            seller = suspend_seller(
                seller=seller,
                actor=actor,
                reason=reason,
                request=request_from_info(info),
            )
        except SellerProfile.DoesNotExist as exc:
            raise GraphQLError("Seller not found.") from exc
        except ValidationError as exc:
            raise validation_error(exc) from exc
        return admin_seller_to_type(seller)

    @strawberry.mutation
    def restore_seller(
        self, info: strawberry.Info, seller_id: strawberry.ID, reason: str
    ) -> AdminSellerType:
        actor = require_staff(info)
        try:
            seller = SellerProfile.objects.select_related("user").get(pk=str(seller_id))
            seller = restore_seller(
                seller=seller,
                actor=actor,
                reason=reason,
                request=request_from_info(info),
            )
        except SellerProfile.DoesNotExist as exc:
            raise GraphQLError("Seller not found.") from exc
        except ValidationError as exc:
            raise validation_error(exc) from exc
        return admin_seller_to_type(seller)
