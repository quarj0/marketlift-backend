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
