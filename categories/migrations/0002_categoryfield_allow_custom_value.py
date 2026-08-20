from django.db import migrations, models


def enable_default_flexible_choices(apps, schema_editor):
    CategoryField = apps.get_model("categories", "CategoryField")
    CategoryField.objects.filter(
        category__slug="phones",
        key__in=("brand", "storage_gb"),
    ).update(allow_custom_value=True)


def disable_default_flexible_choices(apps, schema_editor):
    CategoryField = apps.get_model("categories", "CategoryField")
    CategoryField.objects.filter(
        category__slug="phones",
        key__in=("brand", "storage_gb"),
    ).update(allow_custom_value=False)


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="categoryfield",
            name="allow_custom_value",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            enable_default_flexible_choices,
            reverse_code=disable_default_flexible_choices,
        ),
    ]
