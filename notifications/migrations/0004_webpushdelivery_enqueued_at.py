from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0003_web_push"),
    ]

    operations = [
        migrations.AddField(
            model_name="webpushdelivery",
            name="enqueued_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
