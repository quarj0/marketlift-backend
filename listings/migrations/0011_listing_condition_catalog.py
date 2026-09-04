from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("listings", "0010_listing_condition_labels"),
    ]

    operations = [
        migrations.AlterField(
            model_name="listing",
            name="condition",
            field=models.CharField(
                blank=True,
                choices=[
                    ("Brand New", "Brand New"),
                    ("Refurbished", "Refurbished"),
                    ("Used", "Used"),
                    ("Foreign Used", "Foreign Used"),
                    ("Local Used", "Local Used"),
                    ("Fairly Used", "Fairly Used"),
                    ("Newly-Built", "Newly-Built"),
                    ("Off-Plan", "Off-Plan"),
                    ("Old", "Old"),
                    ("Renovated", "Renovated"),
                    ("Uncompleted Building", "Uncompleted Building"),
                    ("Under construction", "Under construction"),
                ],
                max_length=32,
            ),
        ),
    ]
