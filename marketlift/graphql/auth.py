import strawberry
from graphql import GraphQLError

from accounts.models import User
from sellers.models import SellerProfile


def request_from_info(info: strawberry.Info):
    return getattr(info.context, "request", info.context)


def request_user(info: strawberry.Info):
    return getattr(request_from_info(info), "user", None)


def require_user(info: strawberry.Info):
    user = request_user(info)
    if not user or not user.is_authenticated:
        raise GraphQLError("Authentication required.")
    return user


def effective_admin_role(user) -> str | None:
    if not user or not getattr(user, "is_staff", False):
        return None
    if getattr(user, "is_superuser", False):
        return User.AdminRole.SUPER_ADMIN
    # Backward compatibility for staff created before role support. New staff
    # should always receive an explicit role.
    return user.admin_role or User.AdminRole.ADMIN


def require_staff(
    info: strawberry.Info, roles: set[str] | tuple[str, ...] | None = None
):
    user = require_user(info)
    if not user.is_staff:
        raise GraphQLError("Admin permission required.")
    if roles is not None:
        role = effective_admin_role(user)
        allowed = set(roles) | {User.AdminRole.SUPER_ADMIN}
        if role not in allowed:
            raise GraphQLError("You do not have permission for this admin action.")
    return user


def require_seller(info: strawberry.Info):
    user = require_user(info)
    try:
        return user.seller_profile
    except SellerProfile.DoesNotExist as exc:
        raise GraphQLError("Activate selling before using seller actions.") from exc
