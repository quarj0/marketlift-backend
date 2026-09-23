from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("platform_settings", "0004_min_listing_images")]

    operations = [
        migrations.AlterField(
            model_name="platformconfiguration",
            name="min_listing_images",
            field=models.PositiveIntegerField(default=3),
        ),
        migrations.AlterField(
            model_name="platformconfiguration",
            name="max_listing_images",
            field=models.PositiveIntegerField(default=6),
        ),
        migrations.RunSQL(
            "UPDATE platform_settings_platformconfiguration SET min_listing_images = 3, max_listing_images = 6;",
            migrations.RunSQL.noop,
        ),
    ]
