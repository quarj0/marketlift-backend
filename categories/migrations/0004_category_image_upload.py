from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("uploads", "0002_processing_variants_support"),
        ("categories", "0003_alter_category_pricing_label"),
    ]

    operations = [
        migrations.AddField(
            model_name="category",
            name="image_upload",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="category_visuals",
                to="uploads.uploadasset",
            ),
        ),
    ]
