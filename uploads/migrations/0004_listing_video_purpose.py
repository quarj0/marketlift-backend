from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("uploads", "0003_alter_uploadasset_purpose")]

    operations = [
        migrations.AlterField(
            model_name="uploadasset",
            name="purpose",
            field=models.CharField(
                choices=[
                    ("listing_image", "Listing image"),
                    ("listing_video", "Listing video"),
                    ("message_image", "Message image"),
                    ("verification_document", "Verification document"),
                    ("verification_selfie", "Verification selfie"),
                    ("report_evidence", "Report evidence"),
                    ("avatar", "Avatar"),
                    ("category_image", "Category image"),
                    ("support_attachment", "Support attachment"),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
    ]
