from django.db import migrations, models


def forwards(apps, schema_editor):
    Listing = apps.get_model("listings", "Listing")
    Listing.objects.filter(condition="New").update(condition="Brand New")
    Listing.objects.filter(condition="Like new").update(condition="Refurbished")


def backwards(apps, schema_editor):
    Listing = apps.get_model("listings", "Listing")
    Listing.objects.filter(condition="Brand New").update(condition="New")
    Listing.objects.filter(condition="Refurbished").update(condition="Like new")


class Migration(migrations.Migration):
    dependencies = [
        ("listings", "0009_alter_listing_country_code"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="listing",
            name="condition",
            field=models.CharField(
                blank=True,
                choices=[
                    ("Brand New", "Brand New"),
                    ("Refurbished", "Refurbished"),
                    ("Used", "Used"),
                ],
                max_length=16,
            ),
        ),
    ]
