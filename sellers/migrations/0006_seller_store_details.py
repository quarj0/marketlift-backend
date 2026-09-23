from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sellers", "0005_sellerprofile_country_code")]

    operations = [
        migrations.AddField(
            model_name="sellerprofile",
            name="store_address",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="sellerprofile",
            name="opens_at",
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="sellerprofile",
            name="closes_at",
            field=models.TimeField(blank=True, null=True),
        ),
    ]
