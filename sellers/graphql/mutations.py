import strawberry
from django.core.exceptions import ValidationError
from marketlift.graphql.auth import (
    request_from_info,
    require_staff,
    require_seller,
    require_user,
)
from marketlift.graphql.errors import domain_error, not_found_error, validation_error
from sellers.models import SellerProfile, SellerSettings
from sellers.services import (
    follow_seller,
    restore_seller,
    suspend_seller,
    unfollow_seller,
)
from .mappers import admin_seller_to_type, seller_to_type
from .types import AdminSellerType, SellerSettingsInput, SellerSettingsType, SellerType


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
        from platform_settings.models import PlatformConfiguration

        if not PlatformConfiguration.load().allow_seller_activation:
            raise domain_error(
                "Seller activation is temporarily disabled.",
                code="SELLER_ACTIVATION_DISABLED",
                status=409,
            )
        if seller_type not in SellerProfile.SellerType.values:
            raise domain_error(
                "Invalid seller type.", code="INVALID_SELLER_TYPE", status=422
            )
        seller, created = SellerProfile.objects.get_or_create(
            user=user,
            defaults={"seller_type": seller_type, "display_name": display_name.strip()},
        )
        if not created:
            seller.seller_type = seller_type
            seller.display_name = display_name.strip() or seller.display_name
            seller.save(update_fields=("seller_type", "display_name", "updated_at"))
        SellerSettings.objects.get_or_create(user_profile=seller)
        return seller_to_type(seller)

    @strawberry.mutation
    def update_my_seller_settings(
        self, info: strawberry.Info, input: SellerSettingsInput
    ) -> SellerSettingsType:
        seller = require_seller(info)
        x = SellerSettings.objects.get_or_create(user_profile=seller)[0]
        for k in (
            "new_inquiry",
            "listing_status",
            "performance",
            "auto_renew",
            "show_phone",
            "vacation",
        ):
            v = getattr(input, k)
            if v is not None:
                setattr(x, k, v)
        x.save()
        return SellerSettingsType(
            new_inquiry=x.new_inquiry,
            listing_status=x.listing_status,
            performance=x.performance,
            auto_renew=x.auto_renew,
            show_phone=x.show_phone,
            vacation=x.vacation,
        )

    @strawberry.mutation
    def follow_seller(
        self, info: strawberry.Info, seller_id: strawberry.ID
    ) -> SellerType:
        user = require_user(info)
        try:
            seller = SellerProfile.objects.select_related("user").get(
                pk=str(seller_id), is_suspended=False, user__is_active=True
            )
            return seller_to_type(follow_seller(user=user, seller=seller))
        except SellerProfile.DoesNotExist as exc:
            raise not_found_error("Seller", code="SELLER_NOT_FOUND") from exc
        except ValidationError as exc:
            raise validation_error(exc, code="SELLER_VALIDATION_ERROR") from exc

    @strawberry.mutation
    def unfollow_seller(
        self, info: strawberry.Info, seller_id: strawberry.ID
    ) -> SellerType:
        user = require_user(info)
        try:
            seller = SellerProfile.objects.select_related("user").get(pk=str(seller_id))
            return seller_to_type(unfollow_seller(user=user, seller=seller))
        except SellerProfile.DoesNotExist as exc:
            raise not_found_error("Seller", code="SELLER_NOT_FOUND") from exc

    @strawberry.mutation
    def suspend_seller(
        self, info: strawberry.Info, seller_id: strawberry.ID, reason: str
    ) -> AdminSellerType:
        actor = require_staff(info, roles={"admin", "moderator"})
        try:
            s = SellerProfile.objects.select_related("user").get(pk=str(seller_id))
            return admin_seller_to_type(
                suspend_seller(
                    seller=s,
                    actor=actor,
                    reason=reason,
                    request=request_from_info(info),
                )
            )
        except SellerProfile.DoesNotExist:
            raise not_found_error("Seller", code="SELLER_NOT_FOUND")
        except ValidationError as e:
            raise validation_error(e, code="SELLER_VALIDATION_ERROR")

    @strawberry.mutation
    def restore_seller(
        self, info: strawberry.Info, seller_id: strawberry.ID, reason: str
    ) -> AdminSellerType:
        actor = require_staff(info, roles={"admin", "moderator"})
        try:
            s = SellerProfile.objects.select_related("user").get(pk=str(seller_id))
            return admin_seller_to_type(
                restore_seller(
                    seller=s,
                    actor=actor,
                    reason=reason,
                    request=request_from_info(info),
                )
            )
        except SellerProfile.DoesNotExist:
            raise not_found_error("Seller", code="SELLER_NOT_FOUND")
        except ValidationError as e:
            raise validation_error(e, code="SELLER_VALIDATION_ERROR")
