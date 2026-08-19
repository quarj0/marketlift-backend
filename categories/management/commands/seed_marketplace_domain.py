import json
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from categories.models import Category, CategoryField, CategoryFieldOption
from promotions.models import PromotionProduct
from subscriptions.models import SellerPlan


class Command(BaseCommand):
    help = "Seed Marketlift categories, category fields, seller plans, and promotion products."

    @transaction.atomic
    def handle(self, *args, **options):
        base_dir = Path(__file__).resolve().parents[2]
        project_dir = base_dir.parent

        category_data = json.loads(
            (base_dir / "data" / "category_config.json").read_text()
        )
        plans_data = json.loads(
            (project_dir / "subscriptions" / "data" / "plans.json").read_text()
        )
        products_data = json.loads(
            (project_dir / "promotions" / "data" / "products.json").read_text()
        )

        category_count = self._seed_categories(category_data)
        plan_count = self._seed_plans(plans_data)
        product_count = self._seed_products(products_data)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {category_count} categories, {plan_count} seller plans, "
                f"and {product_count} promotion products."
            )
        )

    def _seed_categories(self, category_data):
        for category_index, item in enumerate(category_data):
            category, _ = Category.objects.update_or_create(
                slug=item["id"],
                defaults={
                    "name": item["name"],
                    "icon": item.get("icon", ""),
                    "description": item.get("description", ""),
                    "active": True,
                    "sort_order": category_index,
                    "schema_version": item.get("schemaVersion", 1),
                    "pricing_mode": item.get("pricing", {}).get("mode", "required"),
                    "pricing_label": item.get("pricing", {}).get("label", "Price (R$)"),
                    "pricing_placeholder": item.get("pricing", {}).get(
                        "placeholder", ""
                    ),
                    "condition_enabled": item.get("condition", {}).get("enabled", True),
                    "condition_required": item.get("condition", {}).get(
                        "required", True
                    ),
                },
            )

            seen_field_keys = []
            for field_index, field_data in enumerate(item.get("fields", [])):
                field, _ = CategoryField.objects.update_or_create(
                    category=category,
                    key=field_data["id"],
                    defaults={
                        "label": field_data["label"],
                        "field_type": field_data["type"],
                        "required": field_data.get("required", False),
                        "filterable": field_data.get("filterable", False),
                        "placeholder": field_data.get("placeholder", ""),
                        "help_text": field_data.get("helpText", ""),
                        "unit": field_data.get("unit", ""),
                        "min_value": self._decimal_or_none(field_data.get("min")),
                        "max_value": self._decimal_or_none(field_data.get("max")),
                        "step_value": self._decimal_or_none(field_data.get("step")),
                        "sort_order": field_index,
                    },
                )
                seen_field_keys.append(field.key)

                seen_options = []
                for option_index, option_data in enumerate(
                    field_data.get("options", [])
                ):
                    option, _ = CategoryFieldOption.objects.update_or_create(
                        field=field,
                        value=option_data["value"],
                        defaults={
                            "label": option_data["label"],
                            "sort_order": option_index,
                        },
                    )
                    seen_options.append(option.value)
                field.options.exclude(value__in=seen_options).delete()

            category.fields.exclude(key__in=seen_field_keys).delete()
        return len(category_data)

    def _seed_plans(self, plans_data):
        for index, item in enumerate(plans_data):
            SellerPlan.objects.update_or_create(
                code=item["code"],
                defaults={
                    "name": item["name"],
                    "monthly_price": Decimal(item["monthly_price"]),
                    "yearly_price": Decimal(item["yearly_price"]),
                    "listing_limit": item["listing_limit"],
                    "promotion_credits": item["promotion_credits"],
                    "features": item["features"],
                    "visibility_weight": Decimal(item["visibility_weight"]),
                    "recommended": item.get("recommended", False),
                    "active": True,
                    "sort_order": index,
                },
            )
        return len(plans_data)

    def _seed_products(self, products_data):
        for index, item in enumerate(products_data):
            PromotionProduct.objects.update_or_create(
                code=item["code"],
                defaults={
                    "name": item["name"],
                    "description": item["description"],
                    "duration_days": item["duration_days"],
                    "price": Decimal(item["price"]),
                    "active": True,
                    "sort_order": index,
                },
            )
        return len(products_data)

    @staticmethod
    def _decimal_or_none(value):
        return None if value is None else Decimal(str(value))
