import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from accounts.models import User
from .graphql.mappers import category_to_type
from .models import (
    Category,
    CategoryField,
    CategoryFieldOption,
    CategoryFieldOptionDependency,
)
from .options import option_is_current


class CurrentYearOptionTests(SimpleTestCase):
    def test_future_year_appears_automatically_when_calendar_catches_up(self):
        field = SimpleNamespace(key="year")
        current = SimpleNamespace(value=str(date.today().year))
        future = SimpleNamespace(value=str(date.today().year + 1))

        self.assertTrue(option_is_current(field, current))
        self.assertFalse(option_is_current(field, future))


class CategoryTaxonomyCurationTests(TestCase):
    def test_legacy_duplicates_are_deactivated_idempotently(self):
        for slug in (
            "home",
            "business",
            "manufacturing-materials-supplies",
            "retail-store-equipment",
            "salon-beauty-equipment",
            "stage-event-equipment",
        ):
            Category.objects.create(name=slug.replace("-", " ").title(), slug=slug)

        call_command("curate_marketplace_taxonomy", verbosity=0)
        call_command("curate_marketplace_taxonomy", verbosity=0)

        self.assertFalse(
            Category.objects.filter(
                slug__in=(
                    "home",
                    "business",
                    "manufacturing-materials-supplies",
                    "retail-store-equipment",
                    "salon-beauty-equipment",
                    "stage-event-equipment",
                ),
                active=True,
            ).exists()
        )
        self.assertEqual(Category.objects.filter(parent=None, active=True).count(), 14)

    def test_hierarchy_repair_restores_parent_without_overwriting_admin_metadata(self):
        call_command("curate_marketplace_taxonomy", verbosity=0)
        cats = Category.objects.get(slug="cats")
        cats.parent = None
        cats.name = "Custom Cats"
        cats.icon = "CustomIcon"
        cats.active = False
        cats.save(update_fields=("parent", "name", "icon", "active", "updated_at"))

        call_command("repair_category_hierarchy", verbosity=0)

        cats.refresh_from_db()
        self.assertEqual(cats.parent.slug, "animals-pets")
        self.assertEqual(cats.name, "Custom Cats")
        self.assertEqual(cats.icon, "CustomIcon")
        self.assertFalse(cats.active)


class CategoryImageSeedSafetyTests(SimpleTestCase):
    def test_unreviewed_image_search_requires_explicit_opt_in(self):
        with self.assertRaisesMessage(CommandError, "not visually reviewed"):
            call_command("seed_distinct_subcategory_images", verbosity=0)


class ReviewedCategoryArtworkPublishTests(SimpleTestCase):
    @override_settings(
        MARKETLIFT_PUBLIC_ASSET_BASE_URL="https://assets.marketlift.com.br"
    )
    def test_audit_validates_the_complete_reviewed_set_without_uploading(self):
        command = __import__(
            "categories.management.commands.publish_reviewed_category_artwork",
            fromlist=["Command"],
        ).Command()
        manifest = command._manifest()
        taxonomy_path = Path(__file__).resolve().parent / "data" / "taxonomy_v2.json"
        taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
        taxonomy_slugs = {item["slug"] for item in taxonomy["roots"]}
        taxonomy_slugs.update(item["slug"] for item in taxonomy["categories"])

        mapped_slugs = [slug for slugs in manifest.values() for slug in slugs]
        self.assertTrue(taxonomy_slugs.issubset(mapped_slugs))
        self.assertEqual(len(mapped_slugs), len(set(mapped_slugs)))

        with TemporaryDirectory() as directory:
            for artwork_key in manifest:
                (Path(directory) / f"{artwork_key}.webp").write_bytes(
                    b"RIFF\x04\x00\x00\x00WEBP"
                )
            call_command(
                "publish_reviewed_category_artwork",
                source_dir=directory,
                audit_only=True,
                verbosity=0,
            )


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


class CategoryAdminMutationHierarchyTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="category-admin@example.com",
            password="test-password",
            full_name="Category Admin",
        )
        self.client.force_login(self.admin)
        self.parent = Category.objects.create(
            slug="animals-test",
            name="Animals Test",
        )
        self.child = Category.objects.create(
            slug="cats-test",
            name="Cats Test",
            parent=self.parent,
        )

    def _update(self, category_input: str):
        return self.client.post(
            "/graphql/",
            data=json.dumps(
                {
                    "query": (
                        "mutation { updateCategory("
                        'categoryId: "cats-test", '
                        f"input: {category_input}"
                        ") { id } }"
                    )
                }
            ),
            content_type="application/json",
        )

    def test_edit_without_parent_preserves_subcategory_hierarchy(self):
        response = self._update('{name: "Renamed Cats"}')

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("errors", response.json())
        self.child.refresh_from_db()
        self.assertEqual(self.child.name, "Renamed Cats")
        self.assertEqual(self.child.parent_id, self.parent.id)

    def test_explicit_null_parent_can_promote_category_to_root(self):
        response = self._update('{name: "Cats Test", parentId: null}')

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("errors", response.json())
        self.child.refresh_from_db()
        self.assertIsNone(self.child.parent_id)


class CatalogSeedSafetyTests(TestCase):
    def test_vehicle_dataset_import_preserves_exact_model_year_dependencies(self):
        call_command("curate_marketplace_taxonomy", verbosity=0)
        with TemporaryDirectory() as directory:
            dataset = Path(directory) / "vehicles.csv"
            dataset.write_text(
                "tipoVeiculo,Marca,Modelo,AnoModelo\n"
                "1,Honda,Civic,2020\n"
                "1,Honda,Civic,2021\n"
                "1,Honda,Fit,2019\n"
                "2,Honda,CG 160,2024\n",
                encoding="utf-8",
            )
            call_command(
                "import_vehicle_catalog_dataset",
                dataset,
                verbosity=0,
            )

        cars = Category.objects.get(slug="cars")
        make = cars.fields.get(key="make")
        model = cars.fields.get(key="model")
        year = cars.fields.get(key="year")
        honda = make.options.get(value="honda")
        civic = model.options.get(value="Civic")
        year_2020 = year.options.get(value="2020")
        year_2019 = year.options.get(value="2019")
        self.assertEqual(model.depends_on_id, make.id)
        self.assertEqual(year.depends_on_id, model.id)
        self.assertTrue(
            CategoryFieldOptionDependency.objects.filter(
                option=civic,
                parent_option=honda,
            ).exists()
        )
        self.assertTrue(
            CategoryFieldOptionDependency.objects.filter(
                option=year_2020,
                parent_option=civic,
            ).exists()
        )
        self.assertFalse(
            CategoryFieldOptionDependency.objects.filter(
                option=year_2019,
                parent_option=civic,
            ).exists()
        )

    def test_vehicle_catalog_cascades_make_model_and_year(self):
        call_command("curate_marketplace_taxonomy", verbosity=0)
        call_command(
            "seed_listing_form_schema_v3",
            verbosity=0,
        )
        call_command(
            "import_product_catalog_pack",
            category=["vehicles"],
            verbosity=0,
        )

        cars = Category.objects.get(slug="cars")
        make = cars.fields.get(key="make")
        model = cars.fields.get(key="model")
        year = cars.fields.get(key="year")
        honda = make.options.get(value="honda", active=True)
        civic = model.options.get(value="Civic", active=True)
        model_year = year.options.get(value="2020", active=True)

        self.assertEqual(model.depends_on_id, make.id)
        self.assertEqual(year.depends_on_id, model.id)
        self.assertTrue(year.lazy_options)
        self.assertTrue(
            CategoryFieldOptionDependency.objects.filter(
                option=civic,
                parent_option=honda,
            ).exists()
        )
        self.assertTrue(
            CategoryFieldOptionDependency.objects.filter(
                option=model_year,
                parent_option=civic,
            ).exists()
        )

    def test_vehicle_compatibility_catalogs_follow_car_make_and_model(self):
        call_command("curate_marketplace_taxonomy", verbosity=0)
        call_command(
            "import_product_catalog_pack",
            category=["vehicles"],
            verbosity=0,
        )
        call_command("seed_vehicle_compatibility_catalogs", verbosity=0)

        for slug, type_key in (
            ("vehicle-parts", "part_type"),
            ("vehicle-accessories", "accessory_type"),
        ):
            category = Category.objects.get(slug=slug)
            make = category.fields.get(key="compatible_make")
            model = category.fields.get(key="compatible_model")
            honda = make.options.get(value="honda")
            civic = model.options.get(value="Civic")
            self.assertEqual(model.depends_on_id, make.id)
            self.assertGreater(category.fields.get(key=type_key).options.count(), 5)
            self.assertTrue(
                CategoryFieldOptionDependency.objects.filter(
                    option=civic,
                    parent_option=honda,
                ).exists()
            )

    def test_animal_catalogs_upgrade_breed_fields_and_cascade_livestock(self):
        call_command("curate_marketplace_taxonomy", verbosity=0)
        call_command(
            "import_product_catalog_pack",
            category=["dogs", "cats", "birds", "livestock"],
            verbosity=0,
        )

        for slug in ("dogs", "cats", "birds"):
            breed = Category.objects.get(slug=slug).fields.get(key="breed_or_type")
            self.assertEqual(breed.field_type, CategoryField.FieldType.SELECT)
            self.assertTrue(breed.lazy_options)
            self.assertTrue(breed.allow_custom_value)
            self.assertGreater(breed.options.filter(active=True).count(), 10)

        livestock = Category.objects.get(slug="livestock")
        animal_type = livestock.fields.get(key="animal_type")
        breed = livestock.fields.get(key="breed_or_type")
        cattle = animal_type.options.get(value="cattle")
        nelore = breed.options.get(value="nelore")
        self.assertEqual(breed.depends_on_id, animal_type.id)
        self.assertLess(animal_type.sort_order, breed.sort_order)
        self.assertTrue(
            CategoryFieldOptionDependency.objects.filter(
                option=nelore,
                parent_option=cattle,
            ).exists()
        )

    def test_other_pet_catalog_cascades_species_and_type(self):
        call_command("curate_marketplace_taxonomy", verbosity=0)
        call_command(
            "import_product_catalog_pack",
            category=["other-pets"],
            verbosity=0,
        )

        category = Category.objects.get(slug="other-pets")
        species = category.fields.get(key="species")
        breed = category.fields.get(key="breed_or_type")
        reptile = species.options.get(value="reptile")
        gecko = breed.options.get(value="gecko")
        self.assertEqual(breed.depends_on_id, species.id)
        self.assertTrue(species.required)
        self.assertTrue(
            CategoryFieldOptionDependency.objects.filter(
                option=gecko,
                parent_option=reptile,
            ).exists()
        )

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
        self.assertTrue(model.options.filter(value="Galaxy Test", active=True).exists())
