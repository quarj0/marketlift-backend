from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.text import slugify

from categories.models import (
    Category,
    CategoryField,
    CategoryFieldOption,
    CategoryFieldOptionDependency,
)

MAX_CATALOG_BYTES = 16 * 1024 * 1024
MAX_CATALOG_ROWS = 250000


def _bool(value, default=False) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    raise ValidationError({"catalog": f"Invalid boolean value: {value}"})


def _value(value: str, label: str) -> str:
    raw = str(value or "").strip()
    derived = raw or slugify(str(label or "").strip())
    if not derived:
        raise ValidationError({"catalog": "Each option needs a value or label."})
    return derived[:120]


@dataclass
class CatalogImportResult:
    rows: int
    fields_created: int
    fields_updated: int
    options_created: int
    options_updated: int
    options_deactivated: int
    dependencies_created: int


def _read_rows(csv_text: str) -> list[dict]:
    if len(csv_text.encode("utf-8")) > MAX_CATALOG_BYTES:
        raise ValidationError({"catalog": "Catalog CSV must be 16 MB or smaller."})

    reader = csv.DictReader(io.StringIO(csv_text))
    required = {"field_key", "field_label", "option_label"}
    headers = set(reader.fieldnames or [])
    missing = sorted(required - headers)
    if missing:
        raise ValidationError({"catalog": "Missing CSV columns: " + ", ".join(missing)})

    rows: list[dict] = []
    for index, raw in enumerate(reader, start=2):
        if len(rows) >= MAX_CATALOG_ROWS:
            raise ValidationError(
                {"catalog": f"Catalogs can contain at most {MAX_CATALOG_ROWS} rows."}
            )
        if not any(str(value or "").strip() for value in raw.values()):
            continue

        field_key = slugify(str(raw.get("field_key") or "").strip())[:80]
        field_label = str(raw.get("field_label") or "").strip()[:120]
        option_label = str(raw.get("option_label") or "").strip()[:120]
        if not field_key or not field_label or not option_label:
            raise ValidationError(
                {
                    "catalog": f"Row {index}: field_key, field_label and option_label are required."
                }
            )

        depends_on = slugify(str(raw.get("depends_on") or "").strip())[:80]
        parent_value = str(raw.get("parent_value") or "").strip()[:120]
        if depends_on and not parent_value:
            raise ValidationError(
                {
                    "catalog": f"Row {index}: parent_value is required when depends_on is set."
                }
            )

        try:
            sort_order = max(0, int(str(raw.get("sort_order") or "0").strip() or 0))
        except ValueError as exc:
            raise ValidationError(
                {"catalog": f"Row {index}: sort_order must be a number."}
            ) from exc

        rows.append(
            {
                "row": index,
                "field_key": field_key,
                "field_label": field_label,
                "depends_on": depends_on,
                "parent_value": parent_value,
                "option_value": _value(raw.get("option_value"), option_label),
                "option_label": option_label,
                "required": _bool(raw.get("required"), False),
                "filterable": _bool(raw.get("filterable"), True),
                "allow_custom": _bool(raw.get("allow_custom"), True),
                "lazy": _bool(raw.get("lazy"), True),
                "active": _bool(raw.get("active"), True),
                "unit": str(raw.get("unit") or "").strip()[:32],
                "sort_order": sort_order,
            }
        )

    if not rows:
        raise ValidationError({"catalog": "The catalog contains no data rows."})
    return rows


@transaction.atomic
def import_category_catalog(
    *, category: Category, csv_text: str, replace_current: bool = True
) -> CatalogImportResult:
    """
    Import a generic cascading-option catalog.

    Omitted options are deactivated (not deleted) when replace_current=True, so
    historic listings keep their stored values while new listing forms stay current.
    """
    rows = _read_rows(csv_text)
    category = Category.objects.select_for_update().get(pk=category.pk)

    definitions: dict[str, dict] = {}
    for row in rows:
        current = definitions.setdefault(
            row["field_key"],
            {
                "label": row["field_label"],
                "depends_on": row["depends_on"],
                "field_order": len(definitions),
                "required": row["required"],
                "filterable": row["filterable"],
                "allow_custom": row["allow_custom"],
                "lazy": row["lazy"],
                "unit": row["unit"],
            },
        )
        if current["depends_on"] != row["depends_on"]:
            raise ValidationError(
                {
                    "catalog": f"Field {row['field_key']} uses more than one parent field."
                }
            )

    existing_fields = {
        field.key: field for field in category.fields.select_for_update().all()
    }
    for key, definition in definitions.items():
        parent_key = definition["depends_on"]
        if (
            parent_key
            and parent_key not in definitions
            and parent_key not in existing_fields
        ):
            raise ValidationError(
                {"catalog": f"Field {key} depends on unknown field {parent_key}."}
            )

    fields_created = 0
    fields_updated = 0
    field_map: dict[str, CategoryField] = dict(existing_fields)

    for key, definition in definitions.items():
        field = field_map.get(key)
        if field is None:
            field = CategoryField.objects.create(
                category=category,
                key=key,
                label=definition["label"],
                field_type=CategoryField.FieldType.SELECT,
                required=definition["required"],
                filterable=definition["filterable"],
                allow_custom_value=definition["allow_custom"],
                lazy_options=definition["lazy"],
                unit=definition["unit"],
                sort_order=definition["field_order"],
            )
            field_map[key] = field
            fields_created += 1
            continue

        changed: list[str] = []
        if field.field_type != CategoryField.FieldType.SELECT:
            if field.field_type not in {
                CategoryField.FieldType.TEXT,
                CategoryField.FieldType.TEXTAREA,
                CategoryField.FieldType.NUMBER,
            }:
                raise ValidationError(
                    {
                        "catalog": (
                            f"Field {key} already exists as {field.field_type}. "
                            "Only text or number fields can be upgraded to catalog choices automatically."
                        )
                    }
                )
            # Historical ListingAttribute rows keep field_type_snapshot and their
            # stored text values. This only changes future input validation/UI.
            field.field_type = CategoryField.FieldType.SELECT
            field.min_value = None
            field.max_value = None
            field.step_value = None
            changed.extend(("field_type", "min_value", "max_value", "step_value"))

        values = {
            "label": definition["label"],
            "required": definition["required"],
            "filterable": definition["filterable"],
            "allow_custom_value": definition["allow_custom"],
            "lazy_options": definition["lazy"],
            "unit": definition["unit"],
            "sort_order": definition["field_order"],
        }
        for attr, value in values.items():
            if getattr(field, attr) != value:
                setattr(field, attr, value)
                changed.append(attr)
        if changed:
            changed.append("updated_at")
            field.save(update_fields=tuple(changed))
            fields_updated += 1

    for key, definition in definitions.items():
        field = field_map[key]
        parent_key = definition["depends_on"]
        parent = field_map.get(parent_key) if parent_key else None
        if parent is not None and parent.field_type != CategoryField.FieldType.SELECT:
            raise ValidationError(
                {"catalog": f"Parent field {parent_key} must be a choice field."}
            )
        if parent is not None and parent.pk == field.pk:
            raise ValidationError({"catalog": f"Field {key} cannot depend on itself."})
        target_id = parent.pk if parent else None
        if field.depends_on_id != target_id:
            field.depends_on = parent
            field.save(update_fields=("depends_on", "updated_at"))
            fields_updated += 1

    imported_values: dict[str, set[str]] = {key: set() for key in definitions}
    options_created = 0
    options_updated = 0
    option_cache: dict[tuple[str, str], CategoryFieldOption] = {}

    for row in rows:
        field = field_map[row["field_key"]]
        imported_values[field.key].add(row["option_value"])
        option_key = (field.key, row["option_value"])
        if option_key in option_cache:
            continue
        option, created = CategoryFieldOption.objects.update_or_create(
            field=field,
            value=row["option_value"],
            defaults={
                "label": row["option_label"],
                "sort_order": row["sort_order"],
                "active": row["active"],
            },
        )
        option_cache[option_key] = option
        options_created += int(created)
        options_updated += int(not created)

    options_deactivated = 0
    if replace_current:
        for key, values in imported_values.items():
            options_deactivated += (
                CategoryFieldOption.objects.filter(field=field_map[key], active=True)
                .exclude(value__in=values)
                .update(active=False)
            )

    imported_option_ids = [option.pk for option in option_cache.values()]
    CategoryFieldOptionDependency.objects.filter(
        option_id__in=imported_option_ids
    ).delete()

    dependency_rows = []
    seen_links: set[tuple[str, str]] = set()
    for row in rows:
        if not row["depends_on"]:
            continue
        child = option_cache[(row["field_key"], row["option_value"])]
        parent_field = field_map[row["depends_on"]]
        parent_value = row["parent_value"]
        parent = option_cache.get((parent_field.key, parent_value))
        if parent is None:
            parent = parent_field.options.filter(value=parent_value).first()
        if parent is None:
            parent = parent_field.options.filter(label__iexact=parent_value).first()
        if parent is None:
            raise ValidationError(
                {
                    "catalog": f"Row {row['row']}: parent option '{parent_value}' does not exist in {parent_field.label}."
                }
            )
        pair = (str(child.pk), str(parent.pk))
        if pair in seen_links:
            continue
        seen_links.add(pair)
        dependency_rows.append(
            CategoryFieldOptionDependency(option=child, parent_option=parent)
        )

    if dependency_rows:
        CategoryFieldOptionDependency.objects.bulk_create(
            dependency_rows, ignore_conflicts=True
        )

    Category.objects.filter(pk=category.pk).update(
        schema_version=category.schema_version + 1
    )

    return CatalogImportResult(
        rows=len(rows),
        fields_created=fields_created,
        fields_updated=fields_updated,
        options_created=options_created,
        options_updated=options_updated,
        options_deactivated=options_deactivated,
        dependencies_created=len(dependency_rows),
    )
