import strawberry
from categories.models import Category
from .mappers import category_to_type
from .types import CategoryType


@strawberry.type
class CategoryQuery:
    @strawberry.field
    def categories(self, active_only: bool = True) -> list[CategoryType]:
        qs = Category.objects.prefetch_related("fields__options", "subcategories")
        if active_only:
            qs = qs.filter(active=True)
        return [category_to_type(item) for item in qs]

    @strawberry.field
    def category(self, id: str) -> CategoryType | None:
        try:
            item = Category.objects.prefetch_related(
                "fields__options", "subcategories"
            ).get(slug=id)
        except Category.DoesNotExist:
            return None
        return category_to_type(item)
