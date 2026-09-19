from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0005_delivery_rider_security"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sellerpaymentaccount",
            name="provider",
            field=models.CharField(default="stripe", max_length=32),
        ),
        migrations.AlterField(
            model_name="commercepayment",
            name="provider",
            field=models.CharField(default="stripe", max_length=32),
        ),
        migrations.AlterField(
            model_name="providerwebhookevent",
            name="provider",
            field=models.CharField(default="stripe", max_length=32),
        ),
    ]
