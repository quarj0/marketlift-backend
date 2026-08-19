from django.db import migrations, models
import django.db.models.deletion, uuid


class Migration(migrations.Migration):
    dependencies = [("uploads", "0001_initial")]
    operations = [
        migrations.AlterField(
            model_name="uploadasset",
            name="purpose",
            field=models.CharField(
                choices=[
                    ("listing_image", "Listing image"),
                    ("message_image", "Message image"),
                    ("verification_document", "Verification document"),
                    ("verification_selfie", "Verification selfie"),
                    ("report_evidence", "Report evidence"),
                    ("avatar", "Avatar"),
                    ("support_attachment", "Support attachment"),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="uploadasset",
            name="processed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="uploadasset",
            name="processing_error",
            field=models.TextField(blank=True),
        ),
        migrations.CreateModel(
            name="UploadVariant",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("kind", models.CharField(max_length=32)),
                ("storage_alias", models.CharField(default="default", max_length=64)),
                ("object_key", models.CharField(max_length=500, unique=True)),
                ("mime_type", models.CharField(default="image/webp", max_length=120)),
                ("size", models.PositiveBigIntegerField(default=0)),
                ("width", models.PositiveIntegerField(default=0)),
                ("height", models.PositiveIntegerField(default=0)),
                (
                    "asset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="variants",
                        to="uploads.uploadasset",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="uploadvariant",
            constraint=models.UniqueConstraint(
                fields=("asset", "kind"), name="uploads_unique_asset_variant"
            ),
        ),
        migrations.AddIndex(
            model_name="uploadvariant",
            index=models.Index(fields=["asset", "kind"], name="uploads_asset_kind_idx"),
        ),
    ]
