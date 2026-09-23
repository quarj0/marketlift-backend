from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("listings", "0011_listing_condition_catalog"),
        ("uploads", "0003_alter_uploadasset_purpose"),
    ]

    operations = [
        migrations.AddField(
            model_name="listing",
            name="video_upload",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="listing_video",
                to="uploads.uploadasset",
            ),
        ),
    ]
