from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from categories.models import Category, CategoryField, CategoryFieldOption


class SeedFipeVehicleMakesCommandTests(TestCase):
    def setUp(self):
        for slug in (
            "cars",
            "motorcycles",
            "trucks-commercial-vehicles",
            "buses-vans",
        ):
            category = Category.objects.create(slug=slug, name=slug)
            field = CategoryField.objects.create(
                category=category,
                key="make",
                label="Make",
                field_type=CategoryField.FieldType.SELECT,
            )
            CategoryFieldOption.objects.create(
                field=field,
                value="starter",
                label="Starter only",
            )

    def test_seeds_only_complete_make_snapshots_for_all_vehicle_categories(self):
        output = StringIO()
        call_command("seed_fipe_vehicle_makes", stdout=output)

        expected = {
            "cars": 107,
            "motorcycles": 103,
            "trucks-commercial-vehicles": 29,
            "buses-vans": 29,
        }
        for slug, count in expected.items():
            field = Category.objects.get(slug=slug).fields.get(key="make")
            self.assertEqual(field.options.filter(active=True).count(), count)
            self.assertFalse(field.options.get(value="starter").active)

        self.assertEqual(
            CategoryFieldOption.objects.filter(field__key="model").count(), 0
        )
        self.assertIn("cars: 107 makes seeded.", output.getvalue())

    def test_dry_run_does_not_change_existing_options(self):
        call_command(
            "seed_fipe_vehicle_makes",
            "--category",
            "cars",
            "--dry-run",
        )

        field = Category.objects.get(slug="cars").fields.get(key="make")
        self.assertEqual(field.options.filter(active=True).count(), 1)
        self.assertTrue(field.options.get(value="starter").active)
