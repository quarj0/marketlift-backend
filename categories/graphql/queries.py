import strawberry
from categories.models import Category
from marketlift.graphql.auth import require_staff
from .mappers import category_to_type
from .types import CategoryType


def _qs():
    return Category.objects.prefetch_related("fields__options", "subcategories")


@strawberry.type
class CategoryQuery:
    @strawberry.field
    def categories(self, active_only: bool = True) -> list[CategoryType]:
        # Public category discovery never exposes disabled categories. `active_only`
        # remains for backwards compatibility but cannot turn this into an admin query.
        return [category_to_type(item) for item in _qs().filter(active=True)]

    @strawberry.field
    def category(self, id: str) -> CategoryType | None:
        try:
            item = _qs().get(slug=id, active=True)
        except Category.DoesNotExist:
            return None
        return category_to_type(item)

    @strawberry.field
    def admin_categories(self, info: strawberry.Info) -> list[CategoryType]:
        require_staff(info, roles={"admin"})
        return [category_to_type(item) for item in _qs()]
