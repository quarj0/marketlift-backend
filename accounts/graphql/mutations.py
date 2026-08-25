import strawberry
from django.core.exceptions import ValidationError

from accounts.models import AdminInvitation, User
from accounts.services import (
    change_password,
    deactivate_account,
    get_account_settings,
    reactivate_account,
    suspend_account,
    update_profile,
)
from marketlift.graphql.auth import request_from_info, require_staff, require_user
from accounts.auth_services import create_admin_invitation, revoke_admin_invitation
from marketlift.graphql.errors import (
    conflict_error,
    domain_error,
    not_found_error,
    validation_error,
)
from uploads.models import UploadAsset

from .mappers import (
    admin_invitation_to_type,
    admin_user_to_type,
    settings_to_type,
    user_to_type,
)
from .types import (
    AccountProfileInput,
    AccountSettingsInput,
    AccountSettingsType,
    AccountUserType,
    AdminInvitationType,
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
                "country_code",
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
            raise not_found_error("Upload", code="UPLOAD_NOT_FOUND") from exc
        except ValidationError as exc:
            raise validation_error(exc, code="ACCOUNT_VALIDATION_ERROR")

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
            raise validation_error(exc, code="ACCOUNT_VALIDATION_ERROR")
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
            raise validation_error(exc, code="ACCOUNT_VALIDATION_ERROR")

    @strawberry.mutation
    def deactivate_my_account(self, info: strawberry.Info, reason: str = "") -> bool:
        try:
            return deactivate_account(
                user=require_user(info),
                reason=reason,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(exc, code="ACCOUNT_VALIDATION_ERROR")

    @strawberry.mutation
    def suspend_account(
        self,
        info: strawberry.Info,
        user_id: strawberry.ID,
        reason: str,
    ) -> AdminUserType:
        staff = require_staff(info, roles={"admin", "moderator"})
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
            raise not_found_error("User", code="USER_NOT_FOUND") from exc
        except ValidationError as exc:
            raise validation_error(exc, code="ACCOUNT_VALIDATION_ERROR")

    @strawberry.mutation
    def reactivate_account(
        self,
        info: strawberry.Info,
        user_id: strawberry.ID,
        reason: str,
    ) -> AdminUserType:
        staff = require_staff(info, roles={"admin", "moderator"})
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
            raise not_found_error("User", code="USER_NOT_FOUND") from exc
        except ValidationError as exc:
            raise validation_error(exc, code="ACCOUNT_VALIDATION_ERROR")

    @strawberry.mutation
    def set_admin_role(
        self,
        info: strawberry.Info,
        user_id: strawberry.ID,
        role: str,
        enabled: bool = True,
    ) -> AdminUserType:
        actor = require_staff(info, roles={User.AdminRole.SUPER_ADMIN})
        if role not in User.AdminRole.values:
            raise domain_error(
                "Invalid administrator role.", code="INVALID_ADMIN_ROLE", status=422
            )
        try:
            target = User.objects.get(pk=str(user_id))
        except User.DoesNotExist as exc:
            raise not_found_error("User", code="USER_NOT_FOUND") from exc
        if target.is_superuser and not enabled:
            raise conflict_error(
                "Superuser access cannot be disabled through this action.",
                code="SUPERUSER_ACCESS_PROTECTED",
            )
        target.is_staff = enabled
        target.admin_role = role if enabled else ""
        target.save(update_fields=("is_staff", "admin_role", "updated_at"))
        from audit.services import record_audit_event

        record_audit_event(
            actor=actor,
            action="admin.role_updated",
            target=target,
            target_type="user",
            target_label=target.full_name or target.email,
            metadata={"role": target.admin_role, "enabled": enabled},
            request=request_from_info(info),
        )
        return admin_user_to_type(target)

    @strawberry.mutation
    def invite_administrator(
        self, info: strawberry.Info, email: str, role: str
    ) -> AdminInvitationType:
        actor = require_staff(info, roles={User.AdminRole.SUPER_ADMIN})
        try:
            invitation, _ = create_admin_invitation(
                email=email,
                role=role,
                invited_by=actor,
                request=request_from_info(info),
            )
            return admin_invitation_to_type(invitation)
        except ValidationError as exc:
            raise validation_error(exc, code="ACCOUNT_VALIDATION_ERROR") from exc

    @strawberry.mutation
    def revoke_admin_invitation(
        self, info: strawberry.Info, invitation_id: strawberry.ID
    ) -> AdminInvitationType:
        actor = require_staff(info, roles={User.AdminRole.SUPER_ADMIN})
        try:
            invitation = AdminInvitation.objects.select_related("invited_by").get(
                pk=str(invitation_id)
            )
            return admin_invitation_to_type(
                revoke_admin_invitation(
                    invitation=invitation, actor=actor, request=request_from_info(info)
                )
            )
        except AdminInvitation.DoesNotExist as exc:
            raise not_found_error(
                "Administrator invitation", code="ADMIN_INVITATION_NOT_FOUND"
            ) from exc
        except ValidationError as exc:
            raise validation_error(exc, code="ACCOUNT_VALIDATION_ERROR") from exc
