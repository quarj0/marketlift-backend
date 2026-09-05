import strawberry
from categories.models import Category, CategoryField
from categories.options import option_is_current
from marketlift.graphql.auth import require_staff
from .mappers import category_to_type
from .types import CategoryFieldOptionType, CategoryType


def _qs():
    return Category.objects.select_related("image_upload", "parent").prefetch_related(
        "fields__options",
        "fields__depends_on",
        "image_upload__variants",
        "subcategories__image_upload__variants",
        "subcategories__subcategories__image_upload__variants",
        "subcategories__subcategories__subcategories__image_upload__variants",
    )


@strawberry.type
class CategoryQuery:
    @strawberry.field
    def categories(self, active_only: bool = True) -> list[CategoryType]:
        # Public category discovery never exposes disabled categories. `active_only`
        # remains for backwards compatibility but cannot turn this into an admin query.
        return [
            category_to_type(item)
            for item in _qs().filter(active=True, parent__isnull=True)
        ]

    @strawberry.field
    def category(self, id: str) -> CategoryType | None:
        try:
            item = _qs().get(slug=id, active=True)
        except Category.DoesNotExist:
            return None
        return category_to_type(item)

    @strawberry.field
    def category_field_options(
        self,
        category_id: str,
        field_id: str,
        parent_value: str | None = None,
        search: str | None = None,
        limit: int = 100,
    ) -> list[CategoryFieldOptionType]:
        try:
            field = CategoryField.objects.select_related("category", "depends_on").get(
                category__slug=category_id, category__active=True, key=field_id
            )
        except CategoryField.DoesNotExist:
            return []

        queryset = field.options.filter(active=True)
        if field.depends_on_id:
            parent_value = (parent_value or "").strip()
            if not parent_value:
                return []
            parent_option = field.depends_on.options.filter(
                active=True, value=parent_value
            ).first()
            if parent_option is None:
                parent_option = field.depends_on.options.filter(
                    active=True, label__iexact=parent_value
                ).first()
            if parent_option is None:
                return []
            queryset = queryset.filter(
                allowed_parent_links__parent_option=parent_option
            )

        term = (search or "").strip()
        if term:
            from django.db.models import Q

            queryset = queryset.filter(
                Q(label__icontains=term) | Q(value__icontains=term)
            )

        limit = max(1, min(int(limit), 250))
        return [
            CategoryFieldOptionType(value=item.value, label=item.label)
            for item in queryset.order_by("sort_order", "label").distinct()
            if option_is_current(field, item)
        ][:limit]

    @strawberry.field
    def admin_categories(self, info: strawberry.Info) -> list[CategoryType]:
        require_staff(info, roles={"admin"})
        return [category_to_type(item) for item in _qs().filter(parent__isnull=True)]

    @strawberry.field
    def admin_category(self, info: strawberry.Info, id: str) -> CategoryType | None:
        require_staff(info, roles={"admin"})
        try:
            item = _qs().get(slug=id)
        except Category.DoesNotExist:
            return None
        return category_to_type(item)
