from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.operations import CreateExtension
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("listings", "0006_listing_search_index"),
    ]

    operations = [
        # Local Docker uses a PostGIS image; managed PostgreSQL providers must
        # expose/enable the postgis extension before applying this migration.
        CreateExtension("postgis"),
        migrations.AlterField(
            model_name="listing",
            name="state",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AlterField(
            model_name="listing",
            name="state_code",
            field=models.CharField(blank=True, max_length=8),
        ),
        migrations.AddField(
            model_name="listing",
            name="country_code",
            field=models.CharField(blank=True, db_index=True, max_length=2),
        ),
        migrations.AddField(
            model_name="listing",
            name="location_point",
            field=gis_models.PointField(
                blank=True,
                geography=True,
                null=True,
                spatial_index=True,
                srid=4326,
            ),
        ),
        migrations.AddField(
            model_name="listing",
            name="location_provider",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="listing",
            name="location_provider_id",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddIndex(
            model_name="listing",
            index=models.Index(
                fields=["country_code", "state_code", "city", "status"],
                name="listings_country_loc_idx",
            ),
        ),
    ]
