import strawberry
from graphql import GraphQLError
from categories.models import Category
from marketlift.graphql.auth import require_staff
from .mappers import category_to_type
from .types import CategoryType, DeleteCategoryPayload


@strawberry.type
class CategoryMutation:
    @strawberry.mutation
    def set_category_active(
        self, info: strawberry.Info, category_id: str, active: bool
    ) -> CategoryType:
        require_staff(info)
        try:
            category = Category.objects.prefetch_related(
                "fields__options", "subcategories"
            ).get(slug=category_id)
        except Category.DoesNotExist as exc:
            raise GraphQLError("Category not found.") from exc
        category.active = active
        category.save(update_fields=("active", "updated_at"))
        return category_to_type(category)

    @strawberry.mutation
    def delete_category(
        self, info: strawberry.Info, category_id: str
    ) -> DeleteCategoryPayload:
        require_staff(info)
        try:
            category = Category.objects.get(slug=category_id)
        except Category.DoesNotExist as exc:
            raise GraphQLError("Category not found.") from exc
        affected, slug = category.listings.count(), category.slug
        category.delete()
        return DeleteCategoryPayload(slug=slug, affected_listings=affected)
