from django.core.management import call_command
from django.test import TestCase

from .graphql.mappers import category_to_type
from .models import Category, CategoryField, CategoryFieldOption


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



class CategoryGraphQLTreeTests(TestCase):
    def test_category_mapper_supports_recursive_subcategories(self):
        root = Category.objects.create(
            slug="electronics-test",
            name="Electronics Test",
            active=True,
        )
        child = Category.objects.create(
            slug="phones-test",
            name="Phones Test",
            parent=root,
            active=True,
        )
        Category.objects.create(
            slug="smartphones-test",
            name="Smartphones Test",
            parent=child,
            active=True,
        )

        mapped = category_to_type(
            Category.objects.prefetch_related(
                "fields__options",
                "fields__depends_on",
                "subcategories__subcategories",
            ).get(pk=root.pk)
        )

        self.assertEqual(len(mapped.subcategories), 1)
        self.assertEqual(mapped.subcategories[0].id, "phones-test")
        self.assertEqual(len(mapped.subcategories[0].subcategories), 1)
        self.assertEqual(
            mapped.subcategories[0].subcategories[0].id,
            "smartphones-test",
        )



class CatalogSeedSafetyTests(TestCase):
    def test_force_seed_preserves_catalog_managed_field_shape_and_options(self):
        call_command("seed_marketplace_domain", verbosity=0)

        phones = Category.objects.get(slug="phones")
        brand = phones.fields.get(key="brand")
        model = phones.fields.get(key="model")

        brand.lazy_options = True
        brand.save(update_fields=("lazy_options", "updated_at"))

        model.field_type = CategoryField.FieldType.SELECT
        model.lazy_options = True
        model.depends_on = brand
        model.save(
            update_fields=(
                "field_type",
                "lazy_options",
                "depends_on",
                "updated_at",
            )
        )
        CategoryFieldOption.objects.create(
            field=model,
            value="Galaxy Test",
            label="Galaxy Test",
            active=True,
        )

        call_command(
            "seed_marketplace_domain",
            force_category_schema=True,
            verbosity=0,
        )

        model.refresh_from_db()
        self.assertEqual(model.field_type, CategoryField.FieldType.SELECT)
        self.assertTrue(model.lazy_options)
        self.assertEqual(model.depends_on_id, brand.id)
        self.assertTrue(
            model.options.filter(value="Galaxy Test", active=True).exists()
        )
