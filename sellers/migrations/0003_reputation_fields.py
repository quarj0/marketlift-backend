from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sellers", "0002_sellersettings")]
    operations = [
        migrations.AddField(
            model_name="sellerprofile",
            name="rating_average",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=3),
        ),
        migrations.AddField(
            model_name="sellerprofile",
            name="review_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="sellerprofile",
            name="positive_review_percent",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
    ]
