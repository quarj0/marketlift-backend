from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.text import slugify

from .models import Category, CategoryField, CategoryFieldOption


def category_scope_ids(slug: str) -> list:
    """Return an active category and every active descendant in its subtree."""
    root_id = (
        Category.objects.filter(slug=slug, active=True)
        .values_list("id", flat=True)
        .first()
    )
    if root_id is None:
        return []

    ids = [root_id]
    frontier = [root_id]
    while frontier:
        children = list(
            Category.objects.filter(parent_id__in=frontier, active=True)
            .exclude(id__in=ids)
            .values_list("id", flat=True)
        )
        ids.extend(children)
        frontier = children
    return ids


def _clean_decimal(value, *, label: str):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError({label: "Enter a valid number."}) from exc


def _normalize_options(options: list[dict] | None) -> list[dict]:
    normalized: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(options or []):
        label = str(item.get("label") or "").strip()
        raw_value = str(item.get("value") or "").strip()
        value = raw_value or slugify(label)[:120]
        if not label:
            raise ValidationError({"options": "Every option needs a label."})
        if not value:
            raise ValidationError(
                {"options": f"Could not derive a value for '{label}'."}
            )
        folded = value.casefold()
        if folded in seen:
            raise ValidationError({"options": f"Duplicate option value: {value}."})
        seen.add(folded)
        normalized.append(
            {
                "value": value[:120],
                "label": label[:120],
                "sort_order": max(0, int(item.get("sort_order", index))),
            }
        )
    return normalized


def _validate_field_configuration(
    *,
    field_type: str,
    allow_custom_value: bool,
    options: list[dict],
    lazy_options: bool = False,
):
    if field_type not in CategoryField.FieldType.values:
        raise ValidationError({"type": "Unsupported category field type."})
    if field_type == CategoryField.FieldType.BOOLEAN and allow_custom_value:
        raise ValidationError(
            {"allow_custom_value": "Boolean fields cannot accept custom choices."}
        )
    if (
        field_type == CategoryField.FieldType.SELECT
        and not allow_custom_value
        and not options
        and not lazy_options
    ):
        raise ValidationError(
            {"options": "A strict select field must have at least one option."}
        )


def _bump_schema_version(category: Category) -> None:
    Category.objects.filter(pk=category.pk).update(
        schema_version=category.schema_version + 1
    )
    category.schema_version += 1


def _replace_options(field: CategoryField, options: list[dict]) -> None:
    requested_values = {item["value"] for item in options}
    if (
        field.field_type == CategoryField.FieldType.SELECT
        and not field.allow_custom_value
    ):
        used_values = set(
            field.listing_values.exclude(text_value__isnull=True)
            .exclude(text_value="")
            .values_list("text_value", flat=True)
        )
        removed_in_use = sorted(used_values - requested_values)
        if removed_in_use:
            raise ValidationError(
                {
                    "options": (
                        "Cannot remove strict option values that are already used by listings: "
                        + ", ".join(removed_in_use[:10])
                        + ("…" if len(removed_in_use) > 10 else "")
                    )
                }
            )

    for item in options:
        CategoryFieldOption.objects.update_or_create(
            field=field,
            value=item["value"],
            defaults={
                "label": item["label"],
                "sort_order": item["sort_order"],
                "active": True,
            },
        )
    field.options.exclude(value__in=requested_values).delete()


@transaction.atomic
def create_category_field(
    *,
    category: Category,
    key: str,
    label: str,
    field_type: str,
    required: bool = False,
    filterable: bool = False,
    allow_custom_value: bool = False,
    depends_on_key: str | None = None,
    lazy_options: bool = False,
    placeholder: str = "",
    help_text: str = "",
    ui_group: str = "",
    unit: str = "",
    min_value=None,
    max_value=None,
    step_value=None,
    sort_order: int = 0,
    options: list[dict] | None = None,
) -> CategoryField:
    clean_key = slugify(key.strip())[:80]
    clean_label = label.strip()
    if not clean_key or not clean_label:
        raise ValidationError({"field": "Field key and label are required."})

    normalized_options = _normalize_options(options)
    _validate_field_configuration(
        field_type=field_type,
        allow_custom_value=allow_custom_value,
        options=normalized_options,
        lazy_options=lazy_options,
    )

    depends_on = None
    if depends_on_key:
        try:
            depends_on = category.fields.get(key=depends_on_key)
        except CategoryField.DoesNotExist as exc:
            raise ValidationError(
                {"depends_on": "The selected parent question does not exist."}
            ) from exc

    field = CategoryField(
        category=category,
        key=clean_key,
        label=clean_label,
        field_type=field_type,
        required=required,
        filterable=filterable,
        allow_custom_value=(
            allow_custom_value
            if field_type == CategoryField.FieldType.SELECT
            else False
        ),
        depends_on=depends_on,
        lazy_options=(
            bool(lazy_options)
            if field_type == CategoryField.FieldType.SELECT
            else False
        ),
        placeholder=placeholder.strip(),
        help_text=help_text.strip(),
        ui_group=ui_group.strip(),
        unit=unit.strip(),
        min_value=_clean_decimal(min_value, label="min_value"),
        max_value=_clean_decimal(max_value, label="max_value"),
        step_value=_clean_decimal(step_value, label="step_value"),
        sort_order=max(0, sort_order),
    )
    field.full_clean()
    field.save()
    _replace_options(field, normalized_options)
    _bump_schema_version(category)
    return CategoryField.objects.prefetch_related("options").get(pk=field.pk)


@transaction.atomic
def update_category_field(
    *,
    field: CategoryField,
    key: str,
    label: str,
    field_type: str,
    required: bool = False,
    filterable: bool = False,
    allow_custom_value: bool = False,
    depends_on_key: str | None = None,
    lazy_options: bool = False,
    placeholder: str = "",
    help_text: str = "",
    ui_group: str = "",
    unit: str = "",
    min_value=None,
    max_value=None,
    step_value=None,
    sort_order: int = 0,
    options: list[dict] | None = None,
) -> CategoryField:
    field = (
        CategoryField.objects.select_for_update()
        .select_related("category")
        .get(pk=field.pk)
    )
    clean_key = slugify(key.strip())[:80]
    clean_label = label.strip()
    if not clean_key or not clean_label:
        raise ValidationError({"field": "Field key and label are required."})

    has_values = field.listing_values.exists()
    if has_values and clean_key != field.key:
        raise ValidationError(
            {"key": "A field key cannot be changed after listings use it."}
        )
    if has_values and field_type != field.field_type:
        raise ValidationError(
            {"type": "A field type cannot be changed after listings use it."}
        )

    if options is None:
        normalized_options = [
            {
                "value": option.value,
                "label": option.label,
                "sort_order": option.sort_order,
            }
            for option in field.options.all()
        ]
    else:
        normalized_options = _normalize_options(options)
    _validate_field_configuration(
        field_type=field_type,
        allow_custom_value=allow_custom_value,
        options=normalized_options,
        lazy_options=lazy_options,
    )

    depends_on = None
    if depends_on_key:
        try:
            depends_on = field.category.fields.exclude(pk=field.pk).get(
                key=depends_on_key
            )
        except CategoryField.DoesNotExist as exc:
            raise ValidationError(
                {"depends_on": "The selected parent question does not exist."}
            ) from exc

    field.key = clean_key
    field.label = clean_label
    field.field_type = field_type
    field.required = required
    field.filterable = filterable
    field.allow_custom_value = (
        allow_custom_value if field_type == CategoryField.FieldType.SELECT else False
    )
    field.depends_on = depends_on
    field.lazy_options = (
        bool(lazy_options) if field_type == CategoryField.FieldType.SELECT else False
    )
    field.placeholder = placeholder.strip()
    field.help_text = help_text.strip()
    field.ui_group = ui_group.strip()
    field.unit = unit.strip()
    field.min_value = _clean_decimal(min_value, label="min_value")
    field.max_value = _clean_decimal(max_value, label="max_value")
    field.step_value = _clean_decimal(step_value, label="step_value")
    field.sort_order = max(0, sort_order)
    field.full_clean()
    field.save()
    if options is not None:
        _replace_options(field, normalized_options)
    _bump_schema_version(field.category)
    return CategoryField.objects.prefetch_related("options").get(pk=field.pk)


@transaction.atomic
def delete_category_field(*, field: CategoryField) -> tuple[str, int]:
    field = (
        CategoryField.objects.select_for_update()
        .select_related("category")
        .get(pk=field.pk)
    )
    key = field.key
    category = field.category
    historical_values = field.listing_values.count()
    field.delete()
    _bump_schema_version(category)
    return key, historical_values
