import strawberry
from graphql import GraphQLError

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


def require_staff(info: strawberry.Info):
    user = require_user(info)
    if not user.is_staff:
        raise GraphQLError("Admin permission required.")
    return user


def require_seller(info: strawberry.Info):
    user = require_user(info)
    try:
        return user.seller_profile
    except SellerProfile.DoesNotExist as exc:
        raise GraphQLError("Activate selling before using seller actions.") from exc
