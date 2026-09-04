from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reports", "0002_report_message_alter_report_target_type")]

    operations = [
        migrations.AlterField(
            model_name="report",
            name="reason",
            field=models.CharField(
                choices=[
                    ("fraud", "Fraud or scam"),
                    ("fake_listing", "Fake listing"),
                    ("incorrect_info", "Incorrect information"),
                    ("prohibited", "Prohibited content"),
                    ("offensive", "Abusive or offensive behaviour"),
                    ("duplicate", "Duplicate or spam"),
                    ("unavailable", "Item no longer available"),
                    ("account", "Account"),
                    ("payment", "Payment"),
                    ("moderation", "Moderation"),
                    ("safety", "Safety"),
                    ("technical", "Technical"),
                    ("other", "Other"),
                ],
                max_length=16,
            ),
        ),
    ]
