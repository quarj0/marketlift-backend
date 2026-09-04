from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("platform_settings", "0003_market_promotionproductmarketprice_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformconfiguration",
            name="min_listing_images",
            field=models.PositiveIntegerField(default=5),
        ),
    ]
