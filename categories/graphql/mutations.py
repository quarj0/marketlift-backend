import strawberry
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from graphql import GraphQLError
from audit.services import record_audit_event
from categories.models import Category
from marketlift.graphql.auth import request_from_info, require_staff
from marketlift.graphql.errors import validation_error
from .mappers import category_to_type
from .types import CategoryAdminInput, CategoryType, DeleteCategoryPayload


def _category_qs():
    return Category.objects.prefetch_related("fields__options", "subcategories")


@strawberry.type
class CategoryMutation:
    @strawberry.mutation
    def create_category(
        self, info: strawberry.Info, input: CategoryAdminInput
    ) -> CategoryType:
        actor = require_staff(info, roles={"admin"})
        name = input.name.strip()
        slug = slugify((input.slug or name).strip())[:80]
        if not name or not slug:
            raise GraphQLError("Category name and slug are required.")
        try:
            parent = (
                Category.objects.get(slug=input.parent_id) if input.parent_id else None
            )
            category = Category(
                name=name,
                slug=slug,
                icon=(input.icon or "").strip(),
                description=(input.description or "").strip(),
                parent=parent,
                active=input.active,
                sort_order=max(0, input.sort_order),
            )
            category.full_clean()
            category.save()
            record_audit_event(
                actor=actor,
                action="category.created",
                target=category,
                target_type="category",
                target_label=category.name,
                request=request_from_info(info),
            )
            return category_to_type(_category_qs().get(pk=category.pk))
        except Category.DoesNotExist as exc:
            raise GraphQLError("Parent category not found.") from exc
        except ValidationError as exc:
            raise validation_error(exc) from exc

    @strawberry.mutation
    def update_category(
        self, info: strawberry.Info, category_id: str, input: CategoryAdminInput
    ) -> CategoryType:
        actor = require_staff(info, roles={"admin"})
        try:
            category = Category.objects.get(slug=category_id)
            parent = (
                Category.objects.get(slug=input.parent_id) if input.parent_id else None
            )
            category.name = input.name.strip()
            category.slug = slugify((input.slug or category.slug).strip())[:80]
            category.icon = (input.icon or "").strip()
            category.description = (input.description or "").strip()
            category.parent = parent
            category.active = input.active
            category.sort_order = max(0, input.sort_order)
            category.full_clean()
            category.save()
            record_audit_event(
                actor=actor,
                action="category.updated",
                target=category,
                target_type="category",
                target_label=category.name,
                request=request_from_info(info),
            )
            return category_to_type(_category_qs().get(pk=category.pk))
        except Category.DoesNotExist as exc:
            raise GraphQLError("Category not found.") from exc
        except ValidationError as exc:
            raise validation_error(exc) from exc

    @strawberry.mutation
    def set_category_active(
        self, info: strawberry.Info, category_id: str, active: bool
    ) -> CategoryType:
        actor = require_staff(info, roles={"admin"})
        try:
            category = _category_qs().get(slug=category_id)
        except Category.DoesNotExist as exc:
            raise GraphQLError("Category not found.") from exc
        category.active = active
        category.save(update_fields=("active", "updated_at"))
        record_audit_event(
            actor=actor,
            action="category.activation_changed",
            target=category,
            target_type="category",
            target_label=category.name,
            metadata={"active": active},
            request=request_from_info(info),
        )
        return category_to_type(category)

    @strawberry.mutation
    def delete_category(
        self, info: strawberry.Info, category_id: str
    ) -> DeleteCategoryPayload:
        actor = require_staff(info, roles={"admin"})
        try:
            category = Category.objects.get(slug=category_id)
        except Category.DoesNotExist as exc:
            raise GraphQLError("Category not found.") from exc
        affected, slug, name = category.listings.count(), category.slug, category.name
        record_audit_event(
            actor=actor,
            action="category.deleted",
            target=category,
            target_type="category",
            target_label=name,
            metadata={"slug": slug, "affectedListings": affected},
            request=request_from_info(info),
        )
        category.delete()
        return DeleteCategoryPayload(slug=slug, affected_listings=affected)
