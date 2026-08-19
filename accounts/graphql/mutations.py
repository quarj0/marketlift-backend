import strawberry
from django.core.exceptions import ValidationError
from graphql import GraphQLError

from accounts.models import User
from accounts.services import (
    change_password,
    deactivate_account,
    get_account_settings,
    reactivate_account,
    suspend_account,
    update_profile,
)
from marketlift.graphql.auth import request_from_info, require_staff, require_user
from marketlift.graphql.errors import validation_error
from uploads.models import UploadAsset

from .mappers import admin_user_to_type, settings_to_type, user_to_type
from .types import (
    AccountProfileInput,
    AccountSettingsInput,
    AccountSettingsType,
    AccountUserType,
    AdminUserType,
)


@strawberry.type
class AccountMutation:
    @strawberry.mutation
    def update_my_profile(
        self,
        info: strawberry.Info,
        input: AccountProfileInput,
    ) -> AccountUserType:
        user = require_user(info)
        data = {
            key: getattr(input, key)
            for key in (
                "full_name",
                "email",
                "phone",
                "bio",
                "state",
                "state_code",
                "city",
                "district",
            )
            if getattr(input, key) is not None
        }
        try:
            upload = (
                UploadAsset.objects.get(pk=str(input.avatar_upload_id))
                if input.avatar_upload_id
                else None
            )
            return user_to_type(
                update_profile(
                    user=user,
                    data=data,
                    avatar_upload=upload,
                    request=request_from_info(info),
                )
            )
        except UploadAsset.DoesNotExist as exc:
            raise GraphQLError("Upload not found.") from exc
        except ValidationError as exc:
            raise validation_error(exc)

    @strawberry.mutation
    def update_my_account_settings(
        self,
        info: strawberry.Info,
        input: AccountSettingsInput,
    ) -> AccountSettingsType:
        settings_obj = get_account_settings(require_user(info))
        for key in (
            "language",
            "email_messages",
            "email_listing_updates",
            "email_recommendations",
            "push_messages",
            "push_listing_updates",
            "marketing_emails",
            "show_phone_to_sellers",
            "show_online_status",
        ):
            value = getattr(input, key)
            if value is not None:
                setattr(settings_obj, key, value)
        try:
            settings_obj.full_clean()
            settings_obj.save()
        except ValidationError as exc:
            raise validation_error(exc)
        return settings_to_type(settings_obj)

    @strawberry.mutation
    def change_my_password(
        self,
        info: strawberry.Info,
        current_password: str,
        new_password: str,
    ) -> bool:
        user = require_user(info)
        try:
            return change_password(
                request=request_from_info(info),
                user=user,
                current_password=current_password,
                new_password=new_password,
            )
        except ValidationError as exc:
            raise validation_error(exc)

    @strawberry.mutation
    def deactivate_my_account(self, info: strawberry.Info, reason: str = "") -> bool:
        try:
            return deactivate_account(
                user=require_user(info),
                reason=reason,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(exc)

    @strawberry.mutation
    def suspend_account(
        self,
        info: strawberry.Info,
        user_id: strawberry.ID,
        reason: str,
    ) -> AdminUserType:
        staff = require_staff(info)
        try:
            target = User.objects.get(pk=str(user_id))
            target = suspend_account(
                actor=staff,
                user=target,
                reason=reason,
                request=request_from_info(info),
            )
            return admin_user_to_type(target)
        except User.DoesNotExist as exc:
            raise GraphQLError("User not found.") from exc
        except ValidationError as exc:
            raise validation_error(exc)

    @strawberry.mutation
    def reactivate_account(
        self,
        info: strawberry.Info,
        user_id: strawberry.ID,
        reason: str,
    ) -> AdminUserType:
        staff = require_staff(info)
        try:
            target = User.objects.get(pk=str(user_id))
            target = reactivate_account(
                actor=staff,
                user=target,
                reason=reason,
                request=request_from_info(info),
            )
            return admin_user_to_type(target)
        except User.DoesNotExist as exc:
            raise GraphQLError("User not found.") from exc
        except ValidationError as exc:
            raise validation_error(exc)
