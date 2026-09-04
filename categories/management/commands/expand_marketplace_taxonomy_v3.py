from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from categories.models import Category, CategoryField, CategoryFieldOption


EXISTING_MOVES = {
    "industrial-machinery": ("Manufacturing Equipment", "Factory", 10),
    "medical-equipment": ("Medical Equipment & Supplies", "Stethoscope", 30),
    "printing-equipment": ("Printing & Graphics Equipment", "Printer", 40),
    "restaurant-equipment": ("Restaurant & Catering Equipment", "CookingPot", 50),
    "office-equipment": ("Stationery & Office Equipment", "BriefcaseBusiness", 90),
    "safety-equipment": ("Safety Equipment & Protective Gear", "ShieldCheck", 70),
}

NEW_CATEGORIES = {
    "manufacturing-materials-supplies": {
        "name": "Manufacturing Materials & Supplies",
        "icon": "Boxes",
        "sort": 20,
        "options": [
            "Raw Materials",
            "Packaging Materials",
            "Industrial Chemicals",
            "Plastic & Rubber Materials",
            "Metal Materials",
            "Textile Materials",
            "Wood Materials",
            "Production Consumables",
            "Other",
        ],
    },
    "retail-store-equipment": {
        "name": "Retail & Store Equipment",
        "icon": "Store",
        "sort": 60,
        "options": [
            "POS Equipment",
            "Barcode Scanner",
            "Cash Register",
            "Display Shelf",
            "Shopping Trolley / Basket",
            "Display Fridge",
            "Price Labeler",
            "Security Equipment",
            "Store Furniture",
            "Other",
        ],
    },
    "salon-beauty-equipment": {
        "name": "Salon & Beauty Equipment",
        "icon": "Sparkles",
        "sort": 80,
        "options": [
            "Salon Chair",
            "Barber Chair",
            "Hair Dryer",
            "Hair Steamer",
            "Wash Basin",
            "Manicure / Pedicure Equipment",
            "Massage Bed",
            "Beauty Machine",
            "Salon Trolley",
            "Other",
        ],
    },
    "stage-event-equipment": {
        "name": "Stage & Event Equipment",
        "icon": "Music",
        "sort": 85,
        "options": [
            "Stage Equipment",
            "Lighting Equipment",
            "PA / Sound System",
            "Microphone",
            "Speaker",
            "Mixer",
            "Projector / Screen",
            "Tent / Canopy",
            "Event Furniture",
            "Other",
        ],
    },
}


class Command(BaseCommand):
    help = (
        "Expand Commercial Equipment & Tools with the detailed marketplace "
        "subcategory structure used by the listing-form v3 catalog."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def _ensure_select(self, category, key, label, options):
        field, _ = CategoryField.objects.get_or_create(
            category=category,
            key=key,
            defaults={
                "label": label,
                "field_type": CategoryField.FieldType.SELECT,
                "required": True,
                "filterable": True,
                "allow_custom_value": True,
                "sort_order": 0,
            },
        )
        for index, label_value in enumerate(options):
            value = (
                label_value.lower()
                .replace("&", "and")
                .replace("/", "-")
                .replace(" ", "-")
            )
            while "--" in value:
                value = value.replace("--", "-")
            CategoryFieldOption.objects.update_or_create(
                field=field,
                value=value[:120],
                defaults={
                    "label": label_value,
                    "active": True,
                    "sort_order": index,
                },
            )
        return field

    def handle(self, *args, **options):
        parent = Category.objects.filter(slug="commercial-equipments-tools").first()
        if parent is None:
            raise RuntimeError(
                "commercial-equipments-tools does not exist. "
                "Run curate_marketplace_taxonomy first."
            )

        changed = 0
        with transaction.atomic():
            for slug, (name, icon, sort_order) in EXISTING_MOVES.items():
                category = Category.objects.filter(slug=slug).first()
                if category is None:
                    continue
                category.parent = parent
                category.name = name
                category.icon = icon
                category.sort_order = sort_order
                category.save(
                    update_fields=(
                        "parent",
                        "name",
                        "icon",
                        "sort_order",
                        "updated_at",
                    )
                )
                changed += 1

            for slug, spec in NEW_CATEGORIES.items():
                category, created = Category.objects.get_or_create(
                    slug=slug,
                    defaults={
                        "name": spec["name"],
                        "icon": spec["icon"],
                        "parent": parent,
                        "active": True,
                        "sort_order": spec["sort"],
                    },
                )
                if not created:
                    category.parent = parent
                    category.name = spec["name"]
                    category.icon = spec["icon"]
                    category.sort_order = spec["sort"]
                    category.save(
                        update_fields=(
                            "parent",
                            "name",
                            "icon",
                            "sort_order",
                            "updated_at",
                        )
                    )
                self._ensure_select(
                    category,
                    "equipment_type",
                    "Equipment type",
                    spec["options"],
                )
                changed += 1

            office = Category.objects.filter(slug="office-equipment").first()
            if office:
                self._ensure_select(
                    office,
                    "equipment_type",
                    "Equipment type",
                    [
                        "Photocopier",
                        "Printer",
                        "Scanner",
                        "Shredder",
                        "Projector",
                        "Binding Machine",
                        "Laminator",
                        "Paper Cutter",
                        "Whiteboard",
                        "Office Stationery",
                        "POS Equipment",
                        "Other",
                    ],
                )

            self.stdout.write(
                self.style.SUCCESS(
                    f"Marketplace taxonomy extension complete: {changed} categories processed."
                )
            )

            if options["dry_run"]:
                transaction.set_rollback(True)
                self.stdout.write(
                    self.style.WARNING(
                        "Dry run complete. All taxonomy changes rolled back."
                    )
                )
