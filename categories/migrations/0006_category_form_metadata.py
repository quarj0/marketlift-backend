from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0005_dependent_catalog_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="category",
            name="condition_options",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="categoryfield",
            name="ui_group",
            field=models.CharField(blank=True, max_length=80),
        ),
    ]
