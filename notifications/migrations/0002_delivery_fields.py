from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("notifications", "0001_initial")]
    operations = [
        migrations.AddField(
            model_name="notification",
            name="email_sent_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="notification",
            name="delivery_attempts",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="notification",
            name="last_delivery_error",
            field=models.TextField(blank=True),
        ),
    ]
