import importlib
from unittest.mock import MagicMock, patch

from django.apps import apps as django_apps
from django.core.cache import cache
from django.test import TestCase, override_settings

from categories.dynamic_catalogs import fipe, icecat
from categories.dynamic_catalogs.service import enrich_category_field_options
from categories.models import (
    Category,
    CategoryField,
    CategoryFieldOption,
    CategoryFieldOptionDependency,
)


class DynamicCatalogTests(TestCase):
    def setUp(self):
        cache.clear()

    def field(self, category, key, *, parent=None):
        return CategoryField.objects.create(
            category=category,
            key=key,
            label=key.title(),
            field_type=CategoryField.FieldType.SELECT,
            required=True,
            filterable=True,
            allow_custom_value=True,
            lazy_options=True,
            depends_on=parent,
        )

    @patch("categories.dynamic_catalogs.service.fipe.brands")
    def test_fipe_make_options_are_hydrated_without_full_sync(self, brands):
        category = Category.objects.create(slug="cars", name="Cars")
        make = self.field(category, "make")
        brands.return_value = [
            {"code": "25", "name": "Honda"},
            {"code": "59", "name": "VW - VolksWagen"},
        ]

        enrich_category_field_options(make)

        self.assertTrue(make.options.filter(label="Honda", active=True).exists())
        self.assertTrue(
            make.options.filter(label="VW - VolksWagen", active=True).exists()
        )
        brands.assert_called_once_with("cars")

    def test_fipe_make_snapshot_covers_the_full_provider_index(self):
        brands = fipe.brands("cars")

        self.assertGreaterEqual(len(brands), 100)
        self.assertIn({"code": "161", "name": "Chery"}, brands)
        self.assertIn({"code": "245", "name": "CAOA Chery"}, brands)
        self.assertIn({"code": "23", "name": "Chevrolet"}, brands)
        self.assertIn({"code": "59", "name": "Volkswagen"}, brands)

    def test_complete_fipe_make_migration_replaces_the_curated_subset(self):
        category = Category.objects.create(slug="cars", name="Cars")
        make = self.field(category, "make")
        retired = CategoryFieldOption.objects.create(
            field=make,
            value="not-a-fipe-make",
            label="Not a FIPE make",
        )
        migration = importlib.import_module(
            "categories.migrations.0008_seed_complete_fipe_makes"
        )

        migration.seed_complete_fipe_makes(django_apps, None)

        self.assertEqual(make.options.filter(active=True).count(), 107)
        self.assertTrue(make.options.filter(value="chevrolet", active=True).exists())
        self.assertTrue(make.options.filter(value="chery", active=True).exists())
        retired.refresh_from_db()
        self.assertFalse(retired.active)

    @patch("categories.dynamic_catalogs.service.fipe.models")
    @patch("categories.dynamic_catalogs.service.fipe.brands")
    def test_fipe_model_hydration_fetches_only_selected_make(self, brands, models):
        category = Category.objects.create(slug="cars", name="Cars")
        make = self.field(category, "make")
        model = self.field(category, "model", parent=make)
        honda = CategoryFieldOption.objects.create(
            field=make, value="honda", label="Honda"
        )
        brands.return_value = [{"code": "25", "name": "Honda"}]
        models.return_value = [{"code": "7693", "name": "Civic Sedan EXL"}]

        enrich_category_field_options(model, parent_option=honda)

        civic = model.options.get(label="Civic Sedan EXL")
        self.assertTrue(
            CategoryFieldOptionDependency.objects.filter(
                option=civic, parent_option=honda
            ).exists()
        )
        models.assert_called_once_with("cars", "25")

    @patch("categories.dynamic_catalogs.service.fipe.years")
    @patch("categories.dynamic_catalogs.service.fipe.models")
    @patch("categories.dynamic_catalogs.service.fipe.brands")
    def test_fipe_year_hydration_fetches_only_selected_model(
        self, brands, models, years
    ):
        category = Category.objects.create(slug="cars", name="Cars")
        make = self.field(category, "make")
        model = self.field(category, "model", parent=make)
        year = self.field(category, "year", parent=model)
        honda = CategoryFieldOption.objects.create(
            field=make, value="honda", label="Honda"
        )
        civic = CategoryFieldOption.objects.create(
            field=model, value="Civic Sedan EXL", label="Civic Sedan EXL"
        )
        CategoryFieldOptionDependency.objects.create(option=civic, parent_option=honda)
        brands.return_value = [{"code": "25", "name": "Honda"}]
        models.return_value = [{"code": "7693", "name": "Civic Sedan EXL"}]
        years.return_value = [
            {"code": "2027-5", "name": "2027 Flex"},
            {"code": "2026-5", "name": "2026 Flex"},
            {"code": "32000-5", "name": "Zero KM"},
        ]

        enrich_category_field_options(year, parent_option=civic)

        self.assertTrue(year.options.filter(value="2027", active=True).exists())
        self.assertTrue(year.options.filter(value="2026", active=True).exists())
        years.assert_called_once_with("cars", "25", "7693")

    @patch("categories.dynamic_catalogs.service.wikidata.models_for_brand")
    @patch("categories.dynamic_catalogs.service.wikidata.brands_for_category")
    def test_wikidata_adds_models_to_curated_electronics_branch(self, brands, models):
        category = Category.objects.create(slug="phones", name="Phones")
        brand = self.field(category, "brand")
        model = self.field(category, "model", parent=brand)
        samsung = CategoryFieldOption.objects.create(
            field=brand, value="samsung", label="Samsung"
        )
        brands.return_value = [{"id": "Q20716", "name": "Samsung"}]
        models.return_value = [{"id": "Q1", "name": "Galaxy Example"}]

        enrich_category_field_options(model, parent_option=samsung)

        option = model.options.get(label="Galaxy Example")
        self.assertTrue(
            CategoryFieldOptionDependency.objects.filter(
                option=option, parent_option=samsung
            ).exists()
        )
        models.assert_called_once_with("Q22645", "Q20716")

    @override_settings(MARKETLIFT_MARKET_COUNTRY_CODE="BR")
    @patch("categories.dynamic_catalogs.fipe.httpx.get")
    def test_fipe_429_enters_cooldown_instead_of_retry_loop(self, get):
        response = MagicMock()
        response.status_code = 429
        response.headers = {"Retry-After": "600"}
        get.return_value = response

        self.assertIsNone(fipe.models("cars", "1"))
        self.assertIsNone(fipe.models("cars", "1"))
        get.assert_called_once()

    @patch.dict(
        "os.environ",
        {
            "ICECAT_USERNAME": "marketlift",
            "ICECAT_API_TOKEN": "secret-api-token",
            "ICECAT_CONTENT_TOKEN": "secret-content-token",
            "ICECAT_LANGUAGE": "PT",
        },
        clear=False,
    )
    @patch("categories.dynamic_catalogs.icecat.httpx.get")
    def test_icecat_lookup_uses_supported_identifier_and_token_headers(self, get):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"data": {"GeneralInfo": {"IcecatId": "123"}}}
        get.return_value = response

        result = icecat.lookup_product(gtin="7891234567890")

        self.assertEqual(result["GeneralInfo"]["IcecatId"], "123")
        _, kwargs = get.call_args
        self.assertEqual(kwargs["params"]["GTIN"], "7891234567890")
        self.assertEqual(kwargs["params"]["shopname"], "marketlift")
        self.assertEqual(kwargs["params"]["lang"], "PT")
        self.assertEqual(kwargs["headers"]["api-token"], "secret-api-token")
        self.assertEqual(kwargs["headers"]["content-token"], "secret-content-token")
