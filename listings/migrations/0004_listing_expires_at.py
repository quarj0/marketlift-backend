from datetime import timedelta

from django.db import migrations, models


def backfill_expires_at(apps, schema_editor):
    Listing = apps.get_model("listings", "Listing")
    for listing in Listing.objects.filter(
        status="published", published_at__isnull=False, expires_at__isnull=True
    ).iterator():
        listing.expires_at = listing.published_at + timedelta(days=90)
        listing.save(update_fields=("expires_at",))


class Migration(migrations.Migration):
    dependencies = [("listings", "0003_recentlyviewedlisting_search_indexes")]

    operations = [
        migrations.AddField(
            model_name="listing",
            name="expires_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.RunPython(backfill_expires_at, migrations.RunPython.noop),
    ]
