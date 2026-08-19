from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("platform_settings", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="platformconfiguration",
            name="allow_seller_activation",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="platformconfiguration",
            name="admin_email_operational_alerts",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="platformconfiguration",
            name="admin_verification_queue_alerts",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="platformconfiguration",
            name="admin_payment_failure_alerts",
            field=models.BooleanField(default=True),
        ),
    ]
