import json
from pathlib import Path

from django.db import migrations, models
from django.utils.text import slugify

SNAPSHOT = (
    Path(__file__).resolve().parents[1] / "catalog_data" / "fipe_brands_2026_09_07.json"
)
CATEGORY_SCOPES = {
    "cars": "cars",
    "motorcycles": "motorcycles",
    "trucks-commercial-vehicles": "trucks",
    "buses-vans": "trucks",
}
BRAND_ALIASES = {
    "caoa changan": ("caoa-changan", "CAOA Changan"),
    "caoa chery": ("caoa-chery", "CAOA Chery"),
    "caoa chery/chery": ("chery", "Chery"),
    "gm - chevrolet": ("chevrolet", "Chevrolet"),
    "kia motors": ("kia", "Kia"),
    "vw - volkswagen": ("volkswagen", "Volkswagen"),
}


def _makes(rows):
    result = []
    seen = set()
    for row in rows:
        raw_name = " ".join(str(row.get("name") or "").split())
        value, label = BRAND_ALIASES.get(
            raw_name.casefold(),
            (slugify(raw_name)[:120], raw_name[:120]),
        )
        if value and label and value not in seen:
            seen.add(value)
            result.append((value, label))
    return sorted(result, key=lambda item: item[1].casefold())


def seed_complete_fipe_makes(apps, schema_editor):
    Category = apps.get_model("categories", "Category")
    CategoryFieldOption = apps.get_model("categories", "CategoryFieldOption")
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))

    for category_slug, scope in CATEGORY_SCOPES.items():
        category = Category.objects.filter(slug=category_slug).first()
        if category is None:
            continue
        field = category.fields.filter(key="make").first()
        if field is None:
            continue

        makes = _makes(payload["scopes"][scope])
        existing = {option.value: option for option in field.options.all()}
        create = []
        update = []
        active_values = []
        for sort_order, (value, label) in enumerate(makes):
            active_values.append(value)
            option = existing.get(value)
            if option is None:
                create.append(
                    CategoryFieldOption(
                        field_id=field.pk,
                        value=value,
                        label=label,
                        sort_order=sort_order,
                        active=True,
                    )
                )
                continue
            if (
                option.label != label
                or option.sort_order != sort_order
                or not option.active
            ):
                option.label = label
                option.sort_order = sort_order
                option.active = True
                update.append(option)

        if create:
            CategoryFieldOption.objects.bulk_create(create)
        if update:
            CategoryFieldOption.objects.bulk_update(
                update,
                ("label", "sort_order", "active"),
            )
        field.options.exclude(value__in=active_values).update(active=False)
        Category.objects.filter(pk=category.pk).update(
            schema_version=models.F("schema_version") + 1
        )


class Migration(migrations.Migration):
    dependencies = [("categories", "0007_prepare_dynamic_catalog_fields")]

    operations = [
        migrations.RunPython(
            seed_complete_fipe_makes,
            reverse_code=migrations.RunPython.noop,
        )
    ]
