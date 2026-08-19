from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("promotions", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="listingpromotion",
            name="expiry_notified_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        )
    ]
