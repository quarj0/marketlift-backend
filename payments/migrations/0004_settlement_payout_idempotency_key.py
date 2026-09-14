from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0003_marketplace_commerce"),
    ]

    operations = [
        migrations.AddField(
            model_name="settlement",
            name="payout_idempotency_key",
            field=models.CharField(blank=True, db_index=True, max_length=160),
        ),
    ]
