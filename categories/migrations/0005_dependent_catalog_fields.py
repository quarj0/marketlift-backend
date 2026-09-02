import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("categories", "0004_category_image_upload"),
    ]

    operations = [
        migrations.AddField(
            model_name="categoryfield",
            name="depends_on",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="dependent_fields",
                to="categories.categoryfield",
            ),
        ),
        migrations.AddField(
            model_name="categoryfield",
            name="lazy_options",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="categoryfieldoption",
            name="active",
            field=models.BooleanField(db_index=True, default=True),
        ),
        migrations.CreateModel(
            name="CategoryFieldOptionDependency",
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
                (
                    "option",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="allowed_parent_links",
                        to="categories.categoryfieldoption",
                    ),
                ),
                (
                    "parent_option",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="child_option_links",
                        to="categories.categoryfieldoption",
                    ),
                ),
            ],
            options={"ordering": ("option_id", "parent_option_id")},
        ),
        migrations.AddConstraint(
            model_name="categoryfieldoptiondependency",
            constraint=models.UniqueConstraint(
                fields=("option", "parent_option"),
                name="categories_unique_option_parent",
            ),
        ),
    ]
