from django.db import migrations, models


def backfill_brazil_country_code(apps, schema_editor):
    Listing = apps.get_model("listings", "Listing")
    Listing.objects.filter(country_code="").update(country_code="BR")


class Migration(migrations.Migration):
    dependencies = [
        ("listings", "0007_listing_geospatial_location"),
    ]

    operations = [
        migrations.RunPython(backfill_brazil_country_code, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="listing",
            name="country_code",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="BR",
                max_length=2,
            ),
        ),
    ]
