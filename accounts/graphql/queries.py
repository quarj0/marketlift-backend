import strawberry
from django.contrib.auth import get_user_model
from django.db.models import Q

from marketlift.graphql.auth import require_staff, require_user

from .mappers import account_to_type, admin_user_to_type
from .types import AccountType, AdminUserType

User = get_user_model()


@strawberry.type
class AccountQuery:
    @strawberry.field
    def me(self, info: strawberry.Info) -> AccountType:
        return account_to_type(require_user(info))

    @strawberry.field
    def admin_users(
        self,
        info: strawberry.Info,
        search: str | None = None,
        active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AdminUserType]:
        require_staff(info)
        qs = User.objects.select_related("seller_profile").all()
        if search:
            qs = qs.filter(
                Q(full_name__icontains=search)
                | Q(email__icontains=search)
                | Q(phone__icontains=search)
            )
        if active is not None:
            qs = qs.filter(is_active=active)
        return [
            admin_user_to_type(user)
            for user in qs[max(0, offset) : max(0, offset) + max(1, min(limit, 100))]
        ]
