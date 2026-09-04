
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from categories.models import Category, CategoryField, CategoryFieldOption


class Command(BaseCommand):
    help = (
        "Apply Marketlift listing-form schema v3: category-specific conditions, "
        "selector-first bounded fields, and grouped feature checkboxes."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def _descendants(self, root_slug: str) -> list[Category]:
        root = Category.objects.filter(slug=root_slug).first()
        if root is None:
            return []
        result: list[Category] = []
        frontier = [root]
        while frontier:
            parent = frontier.pop(0)
            children = list(Category.objects.filter(parent=parent, active=True))
            result.extend(children)
            frontier.extend(children)
        return result

    def _set_condition(self, category: Category, values: list[str] | None):
        enabled = bool(values)
        normalized = list(values or [])
        changed = (
            category.condition_enabled != enabled
            or category.condition_required != enabled
            or list(category.condition_options or []) != normalized
        )
        if not changed:
            return

        category.condition_enabled = enabled
        category.condition_required = enabled
        category.condition_options = normalized
        category.schema_version += 1
        category.save(
            update_fields=(
                "condition_enabled",
                "condition_required",
                "condition_options",
                "schema_version",
                "updated_at",
            )
        )

    @staticmethod
    def _decimal(value):
        return None if value is None else Decimal(str(value))

    def _upsert_field(self, category: Category, spec: dict):
        key = spec["key"]
        existing = CategoryField.objects.filter(category=category, key=key).first()

        values = {
            "label": spec["label"],
            "field_type": spec["type"],
            "required": bool(spec.get("required", False)),
            "filterable": bool(spec.get("filterable", True)),
            "allow_custom_value": (
                bool(spec.get("allow_custom", False))
                if spec["type"] == CategoryField.FieldType.SELECT
                else False
            ),
            "placeholder": spec.get("placeholder", ""),
            "help_text": spec.get("help_text", ""),
            "unit": spec.get("unit", ""),
            "min_value": self._decimal(spec.get("min")),
            "max_value": self._decimal(spec.get("max")),
            "ui_group": spec.get("ui_group", ""),
        }

        if existing is None:
            field = CategoryField.objects.create(
                category=category,
                key=key,
                lazy_options=False,
                sort_order=category.fields.count() + 10,
                **values,
            )
            changed = True
        else:
            field = existing
            changed = False
            for attr, value in values.items():
                if getattr(field, attr) != value:
                    setattr(field, attr, value)
                    changed = True

            # The v3 schema does not disturb a Brand -> Model catalog unless the
            # field itself is being intentionally converted by a supplied spec.
            if field.field_type != CategoryField.FieldType.SELECT:
                field.depends_on = None
                field.lazy_options = False

            if changed:
                field.save()

        requested_options = spec.get("options")
        options_changed = False
        if (
            requested_options is not None
            and field.field_type == CategoryField.FieldType.SELECT
        ):
            requested_values: set[str] = set()
            for index, item in enumerate(requested_options):
                value = str(item["value"])[:120]
                requested_values.add(value)
                _, created = CategoryFieldOption.objects.update_or_create(
                    field=field,
                    value=value,
                    defaults={
                        "label": str(item.get("label") or value)[:120],
                        "active": True,
                        "sort_order": index,
                    },
                )
                options_changed = options_changed or created

            deactivated = field.options.exclude(
                value__in=requested_values
            ).filter(active=True).update(active=False)
            options_changed = options_changed or bool(deactivated)

        if changed or options_changed:
            category.schema_version += 1
            category.save(update_fields=("schema_version", "updated_at"))

    def _apply_global_color_catalog(self, color_options: list[dict]) -> int:
        color_keys = {"color", "interior_color", "exterior_color"}
        fields = CategoryField.objects.filter(
            category__active=True,
            key__in=color_keys,
        ).select_related("category")
        processed = 0

        for field in fields:
            changed = False
            if field.field_type != CategoryField.FieldType.SELECT:
                field.field_type = CategoryField.FieldType.SELECT
                changed = True
            if not field.allow_custom_value:
                field.allow_custom_value = True
                changed = True
            if not field.filterable:
                field.filterable = True
                changed = True
            if field.depends_on_id is not None:
                field.depends_on = None
                changed = True
            if field.lazy_options:
                field.lazy_options = False
                changed = True

            if changed:
                field.save()

            requested_values: set[str] = set()
            options_changed = False
            for index, item in enumerate(color_options):
                value = str(item["value"])[:120]
                requested_values.add(value)
                option, created = CategoryFieldOption.objects.update_or_create(
                    field=field,
                    value=value,
                    defaults={
                        "label": str(item.get("label") or value)[:120],
                        "active": True,
                        "sort_order": index,
                    },
                )
                options_changed = options_changed or created

            deactivated = field.options.exclude(
                value__in=requested_values
            ).filter(active=True).update(active=False)
            options_changed = options_changed or bool(deactivated)

            if changed or options_changed:
                field.category.schema_version += 1
                field.category.save(
                    update_fields=("schema_version", "updated_at")
                )
            processed += 1

        return processed

    def handle(self, *args, **options):
        path = (
            Path(__file__).resolve().parents[2]
            / "data"
            / "form_schema_v3.json"
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        dry_run = options["dry_run"]

        with transaction.atomic():
            condition_sets = data["conditions"]

            for root_slug, policy_name in data["condition_roots"].items():
                condition_values = condition_sets[policy_name]
                for category in self._descendants(root_slug):
                    self._set_condition(category, condition_values)

            for root_slug in data["condition_disabled_roots"]:
                for category in self._descendants(root_slug):
                    self._set_condition(category, None)

            for slug, policy_name in data["condition_overrides"].items():
                category = Category.objects.filter(slug=slug).first()
                if category is None:
                    self.stdout.write(
                        self.style.WARNING(f"{slug}: category missing; skipped.")
                    )
                    continue
                condition_values = (
                    condition_sets[policy_name] if policy_name else None
                )
                self._set_condition(category, condition_values)

            color_fields = self._apply_global_color_catalog(
                data.get("color_options", [])
            )

            processed = 0
            for slug, specs in data["category_fields"].items():
                category = Category.objects.filter(slug=slug, active=True).first()
                if category is None:
                    continue
                for spec in specs:
                    self._upsert_field(category, spec)
                    processed += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"Listing-form schema v3: {processed} field definitions processed; "
                    f"{color_fields} color fields upgraded."
                )
            )

            if dry_run:
                transaction.set_rollback(True)
                self.stdout.write(
                    self.style.WARNING(
                        "Dry run complete. All schema changes rolled back."
                    )
                )
