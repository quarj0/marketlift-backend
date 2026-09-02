import strawberry
from django.core.exceptions import ValidationError
from django.utils.text import slugify

from audit.services import record_audit_event
from categories.models import Category, CategoryField
from categories.catalogs import import_category_catalog
from categories.services import (
    create_category_field,
    delete_category_field,
    update_category_field,
)
from marketlift.graphql.auth import request_from_info, require_staff
from uploads.models import UploadAsset
from uploads.services import claim_upload, retire_upload
from marketlift.markets.defaults import default_pricing_label
from marketlift.graphql.errors import domain_error, not_found_error, validation_error

from .mappers import category_to_type
from .types import (
    CategoryAdminInput,
    CategoryCatalogImportPayload,
    CategoryFieldAdminInput,
    CategoryFieldDefinitionType,
    CategoryType,
    DeleteCategoryFieldPayload,
    DeleteCategoryPayload,
)


def _category_qs():
    return Category.objects.select_related("image_upload").prefetch_related("fields__options", "fields__depends_on", "image_upload__variants", "subcategories__image_upload__variants")


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
        "pricing_label": input.pricing_label.strip() or default_pricing_label(),
        "pricing_placeholder": (input.pricing_placeholder or "").strip(),
        "condition_enabled": input.condition_enabled,
        "condition_required": input.condition_required,
    }


def _apply_category_image(*, category: Category, input: CategoryAdminInput, actor):
    if input.image_upload_id and input.remove_image:
        raise ValidationError({"image": "Choose a replacement image or remove the current image, not both."})
    old_asset = category.image_upload
    if input.remove_image:
        category.image_upload = None
        return old_asset
    if not input.image_upload_id:
        return None
    try:
        upload = UploadAsset.objects.get(pk=str(input.image_upload_id))
    except (UploadAsset.DoesNotExist, ValueError) as exc:
        raise ValidationError({"image": "The selected category image upload was not found."}) from exc
    category.image_upload = claim_upload(
        asset=upload,
        user=actor,
        purpose=UploadAsset.Purpose.CATEGORY_IMAGE,
    )
    return old_asset


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
            raise domain_error(
                "Category name and slug are required.",
                code="CATEGORY_INPUT_INVALID",
                status=422,
            )
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
            if input.image_upload_id:
                _apply_category_image(category=category, input=input, actor=actor)
                category.save(update_fields=("image_upload", "updated_at"))
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
            raise not_found_error(
                "Parent category", code="PARENT_CATEGORY_NOT_FOUND"
            ) from exc
        except ValidationError as exc:
            raise validation_error(exc, code="CATEGORY_VALIDATION_ERROR") from exc

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
            old_image_asset = _apply_category_image(
                category=category, input=input, actor=actor
            )
            if schema_changed:
                category.schema_version += 1
            category.full_clean()
            category.save()
            if old_image_asset is not None and old_image_asset.pk != category.image_upload_id:
                retire_upload(asset=old_image_asset)
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
            raise not_found_error("Category", code="CATEGORY_NOT_FOUND") from exc
        except ValidationError as exc:
            raise validation_error(exc, code="CATEGORY_VALIDATION_ERROR") from exc

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
                depends_on_key=input.depends_on,
                lazy_options=input.lazy_options,
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
            raise not_found_error("Category", code="CATEGORY_NOT_FOUND") from exc
        except ValidationError as exc:
            raise validation_error(exc, code="CATEGORY_VALIDATION_ERROR") from exc

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
                depends_on_key=input.depends_on,
                lazy_options=input.lazy_options,
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
            raise not_found_error(
                "Category field", code="CATEGORY_FIELD_NOT_FOUND"
            ) from exc
        except ValidationError as exc:
            raise validation_error(exc, code="CATEGORY_VALIDATION_ERROR") from exc

    @strawberry.mutation
    def import_category_catalog_csv(
        self,
        info: strawberry.Info,
        category_id: str,
        csv_text: str,
        replace_current: bool = True,
    ) -> CategoryCatalogImportPayload:
        actor = require_staff(info, roles={"admin"})
        try:
            category = Category.objects.get(slug=category_id)
            result = import_category_catalog(
                category=category,
                csv_text=csv_text,
                replace_current=replace_current,
            )
            category.refresh_from_db(fields=("schema_version",))
            record_audit_event(
                actor=actor,
                action="category.catalog_imported",
                target=category,
                target_type="category",
                target_label=category.name,
                metadata={
                    "rows": result.rows,
                    "fieldsCreated": result.fields_created,
                    "fieldsUpdated": result.fields_updated,
                    "optionsCreated": result.options_created,
                    "optionsUpdated": result.options_updated,
                    "optionsDeactivated": result.options_deactivated,
                    "dependenciesCreated": result.dependencies_created,
                    "schemaVersion": category.schema_version,
                },
                request=request_from_info(info),
            )
            return CategoryCatalogImportPayload(
                rows=result.rows,
                fields_created=result.fields_created,
                fields_updated=result.fields_updated,
                options_created=result.options_created,
                options_updated=result.options_updated,
                options_deactivated=result.options_deactivated,
                dependencies_created=result.dependencies_created,
                schema_version=category.schema_version,
            )
        except Category.DoesNotExist as exc:
            raise not_found_error("Category", code="CATEGORY_NOT_FOUND") from exc
        except ValidationError as exc:
            raise validation_error(
                exc, code="CATEGORY_CATALOG_VALIDATION_ERROR"
            ) from exc

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
            raise not_found_error(
                "Category field", code="CATEGORY_FIELD_NOT_FOUND"
            ) from exc

    @strawberry.mutation
    def set_category_active(
        self, info: strawberry.Info, category_id: str, active: bool
    ) -> CategoryType:
        actor = require_staff(info, roles={"admin"})
        try:
            category = _category_qs().get(slug=category_id)
        except Category.DoesNotExist as exc:
            raise not_found_error("Category", code="CATEGORY_NOT_FOUND") from exc
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
            raise not_found_error("Category", code="CATEGORY_NOT_FOUND") from exc
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
