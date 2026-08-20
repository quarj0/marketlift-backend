import strawberry
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from graphql import GraphQLError

from audit.services import record_audit_event
from categories.models import Category, CategoryField
from categories.services import (
    create_category_field,
    delete_category_field,
    update_category_field,
)
from marketlift.graphql.auth import request_from_info, require_staff
from marketlift.graphql.errors import validation_error

from .mappers import category_to_type
from .types import (
    CategoryAdminInput,
    CategoryFieldAdminInput,
    CategoryFieldDefinitionType,
    CategoryType,
    DeleteCategoryFieldPayload,
    DeleteCategoryPayload,
)


def _category_qs():
    return Category.objects.prefetch_related("fields__options", "subcategories")


def _field_to_type(field: CategoryField) -> CategoryFieldDefinitionType:
    from .mappers import category_to_type

    # Reuse the category mapper so field serialization stays defined in one place.
    category = _category_qs().get(pk=field.category_id)
    return next(
        item for item in category_to_type(category).fields if item.id == field.key
    )


def _option_payload(options):
    if options is None:
        return None
    return [
        {
            "label": option.label,
            "value": option.value,
            "sort_order": index if option.sort_order is None else option.sort_order,
        }
        for index, option in enumerate(options or [])
    ]


def _category_schema_values(input: CategoryAdminInput):
    pricing_mode = input.pricing_mode.strip().lower()
    if pricing_mode not in Category.PricingMode.values:
        raise ValidationError(
            {"pricing_mode": "Pricing mode must be required or optional."}
        )
    if input.condition_required and not input.condition_enabled:
        raise ValidationError(
            {"condition_required": "A disabled condition cannot be required."}
        )
    return {
        "pricing_mode": pricing_mode,
        "pricing_label": input.pricing_label.strip() or "Price (R$)",
        "pricing_placeholder": (input.pricing_placeholder or "").strip(),
        "condition_enabled": input.condition_enabled,
        "condition_required": input.condition_required,
    }


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
            schema_values = _category_schema_values(input)
            category = Category(
                name=name,
                slug=slug,
                icon=(input.icon or "").strip(),
                description=(input.description or "").strip(),
                parent=parent,
                active=input.active,
                sort_order=max(0, input.sort_order),
                **schema_values,
            )
            category.full_clean()
            category.save()
            record_audit_event(
                actor=actor,
                action="category.created",
                target=category,
                target_type="category",
                target_label=category.name,
                metadata={"schemaVersion": category.schema_version},
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
            schema_values = _category_schema_values(input)
            schema_changed = any(
                getattr(category, key) != value for key, value in schema_values.items()
            )
            category.name = input.name.strip()
            category.slug = slugify((input.slug or category.slug).strip())[:80]
            category.icon = (input.icon or "").strip()
            category.description = (input.description or "").strip()
            category.parent = parent
            category.active = input.active
            category.sort_order = max(0, input.sort_order)
            for key, value in schema_values.items():
                setattr(category, key, value)
            if schema_changed:
                category.schema_version += 1
            category.full_clean()
            category.save()
            record_audit_event(
                actor=actor,
                action="category.updated",
                target=category,
                target_type="category",
                target_label=category.name,
                metadata={
                    "schemaChanged": schema_changed,
                    "schemaVersion": category.schema_version,
                },
                request=request_from_info(info),
            )
            return category_to_type(_category_qs().get(pk=category.pk))
        except Category.DoesNotExist as exc:
            raise GraphQLError("Category not found.") from exc
        except ValidationError as exc:
            raise validation_error(exc) from exc

    @strawberry.mutation
    def create_category_field(
        self,
        info: strawberry.Info,
        category_id: str,
        input: CategoryFieldAdminInput,
    ) -> CategoryFieldDefinitionType:
        actor = require_staff(info, roles={"admin"})
        try:
            category = Category.objects.get(slug=category_id)
            field = create_category_field(
                category=category,
                key=input.key,
                label=input.label,
                field_type=input.type,
                required=input.required,
                filterable=input.filterable,
                allow_custom_value=input.allow_custom_value,
                placeholder=input.placeholder or "",
                help_text=input.help_text or "",
                unit=input.unit or "",
                min_value=input.min,
                max_value=input.max,
                step_value=input.step,
                sort_order=input.sort_order,
                options=_option_payload(input.options),
            )
            record_audit_event(
                actor=actor,
                action="category.field_created",
                target=category,
                target_type="category",
                target_label=category.name,
                metadata={
                    "field": field.key,
                    "schemaVersion": field.category.schema_version,
                },
                request=request_from_info(info),
            )
            return _field_to_type(field)
        except Category.DoesNotExist as exc:
            raise GraphQLError("Category not found.") from exc
        except ValidationError as exc:
            raise validation_error(exc) from exc

    @strawberry.mutation
    def update_category_field(
        self,
        info: strawberry.Info,
        category_id: str,
        field_id: str,
        input: CategoryFieldAdminInput,
    ) -> CategoryFieldDefinitionType:
        actor = require_staff(info, roles={"admin"})
        try:
            field = CategoryField.objects.select_related("category").get(
                category__slug=category_id, key=field_id
            )
            field = update_category_field(
                field=field,
                key=input.key,
                label=input.label,
                field_type=input.type,
                required=input.required,
                filterable=input.filterable,
                allow_custom_value=input.allow_custom_value,
                placeholder=input.placeholder or "",
                help_text=input.help_text or "",
                unit=input.unit or "",
                min_value=input.min,
                max_value=input.max,
                step_value=input.step,
                sort_order=input.sort_order,
                options=_option_payload(input.options),
            )
            record_audit_event(
                actor=actor,
                action="category.field_updated",
                target=field.category,
                target_type="category",
                target_label=field.category.name,
                metadata={
                    "field": field.key,
                    "schemaVersion": field.category.schema_version,
                },
                request=request_from_info(info),
            )
            return _field_to_type(field)
        except CategoryField.DoesNotExist as exc:
            raise GraphQLError("Category field not found.") from exc
        except ValidationError as exc:
            raise validation_error(exc) from exc

    @strawberry.mutation
    def delete_category_field(
        self,
        info: strawberry.Info,
        category_id: str,
        field_id: str,
    ) -> DeleteCategoryFieldPayload:
        actor = require_staff(info, roles={"admin"})
        try:
            field = CategoryField.objects.select_related("category").get(
                category__slug=category_id, key=field_id
            )
            category = field.category
            deleted_key, historical_values = delete_category_field(field=field)
            category.refresh_from_db(fields=("schema_version",))
            record_audit_event(
                actor=actor,
                action="category.field_deleted",
                target=category,
                target_type="category",
                target_label=category.name,
                metadata={
                    "field": deleted_key,
                    "historicalValues": historical_values,
                    "schemaVersion": category.schema_version,
                },
                request=request_from_info(info),
            )
            return DeleteCategoryFieldPayload(
                category_id=category.slug,
                field_id=deleted_key,
                historical_values=historical_values,
                schema_version=category.schema_version,
            )
        except CategoryField.DoesNotExist as exc:
            raise GraphQLError("Category field not found.") from exc

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
