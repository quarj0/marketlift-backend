import strawberry
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from graphql import GraphQLError

from marketlift.graphql.auth import request_from_info, require_staff
from marketlift.graphql.errors import validation_error
from accounts.services import reactivate_account, suspend_account

from .mappers import admin_user_to_type
from .types import AdminUserType

User = get_user_model()


def _get_user(user_id: strawberry.ID):
    try:
        return User.objects.get(pk=str(user_id))
    except (User.DoesNotExist, ValueError) as exc:
        raise GraphQLError("User not found.") from exc


@strawberry.type
class AccountMutation:
    @strawberry.mutation
    def suspend_account(
        self, info: strawberry.Info, user_id: strawberry.ID, reason: str
    ) -> AdminUserType:
        actor = require_staff(info)
        try:
            user = suspend_account(
                user=_get_user(user_id),
                actor=actor,
                reason=reason,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(exc) from exc
        return admin_user_to_type(user)

    @strawberry.mutation
    def reactivate_account(
        self, info: strawberry.Info, user_id: strawberry.ID, reason: str
    ) -> AdminUserType:
        actor = require_staff(info)
        try:
            user = reactivate_account(
                user=_get_user(user_id),
                actor=actor,
                reason=reason,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(exc) from exc
        return admin_user_to_type(user)
