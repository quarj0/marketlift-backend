from django.core.management import call_command
from django.test import TestCase

from .models import Category, CategoryField


class CategorySeedTests(TestCase):
    def test_seed_is_idempotent_and_preserves_frontend_schema(self):
        call_command("seed_marketplace_domain", verbosity=0)
        call_command("seed_marketplace_domain", verbosity=0)

        phones = Category.objects.get(slug="phones")
        self.assertEqual(phones.schema_version, 1)
        self.assertEqual(phones.pricing_mode, Category.PricingMode.REQUIRED)
        self.assertTrue(phones.condition_required)
        self.assertEqual(phones.fields.count(), 10)

        brand = phones.fields.get(key="brand")
        self.assertEqual(brand.field_type, CategoryField.FieldType.SELECT)
        self.assertTrue(brand.required)
        self.assertTrue(brand.filterable)
        self.assertEqual(brand.options.count(), 8)
        self.assertTrue(brand.allow_custom_value)

        storage = phones.fields.get(key="storage_gb")
        self.assertTrue(storage.allow_custom_value)

        sim_type = phones.fields.get(key="sim_type")
        self.assertFalse(sim_type.allow_custom_value)

    def test_seed_does_not_overwrite_admin_managed_category_schema_without_force(self):
        call_command("seed_marketplace_domain", verbosity=0)
        phones = Category.objects.get(slug="phones")
        brand = phones.fields.get(key="brand")
        brand.label = "Device brand"
        brand.save(update_fields=("label", "updated_at"))

        call_command("seed_marketplace_domain", verbosity=0)
        brand.refresh_from_db()
        self.assertEqual(brand.label, "Device brand")

        call_command("seed_marketplace_domain", force_category_schema=True, verbosity=0)
        brand.refresh_from_db()
        self.assertEqual(brand.label, "Brand")
