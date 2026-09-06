from django.db import migrations


VEHICLES = {
    "cars": (
        ("make", "Make", None),
        ("model", "Model", "make"),
        ("year", "Model year", "model"),
    ),
    "motorcycles": (
        ("make", "Make", None),
        ("model", "Model", "make"),
        ("year", "Model year", "model"),
    ),
    "trucks-commercial-vehicles": (
        ("make", "Make", None),
        ("model", "Model", "make"),
        ("year", "Model year", "model"),
    ),
    "buses-vans": (
        ("make", "Make", None),
        ("model", "Model", "make"),
        ("year", "Model year", "model"),
    ),
}

ELECTRONICS = {
    "phones",
    "computers",
    "tablets",
    "cameras",
    "gaming",
    "tvs-video",
    "printers-scanners",
    "smart-watches",
    "audio",
    "networking",
    "other-electronics",
    "electronics",
}


def _prepare_field(CategoryField, category, key, label, parent, sort_order):
    field, _ = CategoryField.objects.get_or_create(
        category=category,
        key=key,
        defaults={
            "label": label,
            "field_type": "select",
            "required": key not in {"model"},
            "filterable": True,
            "allow_custom_value": True,
            "lazy_options": True,
            "depends_on": parent,
            "sort_order": sort_order,
        },
    )
    changed = []
    values = {
        "label": label,
        "field_type": "select",
        "filterable": True,
        "allow_custom_value": True,
        "lazy_options": True,
        "depends_on_id": parent.pk if parent else None,
    }
    if key in {"make", "brand"}:
        values["required"] = True
    if key == "model" and category.slug in VEHICLES:
        values["required"] = True
    if key == "year":
        values["required"] = True

    for attr, value in values.items():
        if getattr(field, attr) != value:
            setattr(field, attr, value)
            changed.append(attr)
    if changed:
        field.save(update_fields=tuple(changed) + ("updated_at",))
    return field


def prepare_dynamic_catalog_fields(apps, schema_editor):
    Category = apps.get_model("categories", "Category")
    CategoryField = apps.get_model("categories", "CategoryField")

    for slug, specs in VEHICLES.items():
        category = Category.objects.filter(slug=slug).first()
        if category is None:
            continue
        fields = {}
        for index, (key, label, parent_key) in enumerate(specs):
            parent = fields.get(parent_key) if parent_key else None
            fields[key] = _prepare_field(
                CategoryField, category, key, label, parent, index
            )
        Category.objects.filter(pk=category.pk).update(
            schema_version=category.schema_version + 1
        )

    for slug in ELECTRONICS:
        category = Category.objects.filter(slug=slug).first()
        if category is None:
            continue
        brand = _prepare_field(
            CategoryField, category, "brand", "Brand", None, 10
        )
        _prepare_field(
            CategoryField, category, "model", "Model", brand, 20
        )
        Category.objects.filter(pk=category.pk).update(
            schema_version=category.schema_version + 1
        )


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0006_category_form_metadata"),
    ]

    operations = [
        migrations.RunPython(
            prepare_dynamic_catalog_fields,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
