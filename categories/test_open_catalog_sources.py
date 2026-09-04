import csv
import io
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from categories.management.commands.sync_fipe_vehicle_catalog import (
    _year_from_code,
    fetch_fipe_rows,
)
from categories.management.commands.sync_open_vehicle_catalog import (
    fetch_makes,
    fetch_rows,
)
from categories.management.commands.sync_wikidata_catalogs import (
    _brand_model_csv,
    _breed_csv,
    fetch_brand_models,
    fetch_breeds,
)


def response(payload):
    item = MagicMock()
    item.json.return_value = payload
    return item


class OpenVehicleCatalogTests(SimpleTestCase):
    def test_vpic_make_discovery_supports_categories_without_seeded_makes(self):
        client = MagicMock()
        client.get.return_value = response(
            {"Results": [{"MakeName": "Volvo"}, {"MakeName": "Mercedes-Benz"}]}
        )

        self.assertEqual(
            fetch_makes(client, vehicle_type="buses"),
            ["Mercedes-Benz", "Volvo"],
        )

    def test_vpic_rows_preserve_exact_model_year_combinations(self):
        client = MagicMock()
        client.get.side_effect = [
            response(
                {
                    "Results": [
                        {"Make_Name": "Honda", "Model_Name": "Civic"},
                    ]
                }
            ),
            response({"Results": []}),
        ]

        rows = fetch_rows(
            client,
            vehicle_type="cars",
            makes=["Honda"],
            start_year=2025,
            end_year=2026,
            max_requests=2,
        )

        self.assertEqual(rows, {("Honda", "Civic", 2025)})
        self.assertIn(
            "vehicletype/Passenger%20Car", client.get.call_args_list[0].args[0]
        )


class FipeVehicleCatalogTests(SimpleTestCase):
    def test_future_model_years_are_rejected_until_calendar_reaches_them(self):
        self.assertEqual(_year_from_code("32000-1", current_year=2026), 2026)
        self.assertEqual(_year_from_code("2026-5", current_year=2026), 2026)
        self.assertIsNone(_year_from_code("2027-5", current_year=2026))

    def test_fipe_rows_follow_exact_brand_model_year_combinations(self):
        client = MagicMock()
        client.get.side_effect = [
            response([{"code": "25", "name": "Honda"}]),
            response(
                [
                    {"code": "2027-5", "name": "2027 Flex"},
                    {"code": "2020-5", "name": "2020 Flex"},
                ]
            ),
            response([{"code": "7693", "name": "Civic Sedan EXL"}]),
        ]

        rows, brands, requests = fetch_fipe_rows(
            client,
            vehicle_type="cars",
            requested_brands=["Honda"],
            max_requests=3,
            current_year=2026,
        )

        self.assertEqual(rows, {("Honda", "Civic Sedan EXL", 2020)})
        self.assertEqual(brands, {"Honda"})
        self.assertEqual(requests, 3)
        self.assertIn(
            "/cars/brands/25/years/2020-5/models",
            client.get.call_args_list[-1].args[0],
        )


class WikidataCatalogTests(SimpleTestCase):
    def test_brand_models_are_converted_to_cascading_catalog_rows(self):
        client = MagicMock()
        client.get.return_value = response(
            {
                "results": {
                    "bindings": [
                        {
                            "model": {"value": "http://www.wikidata.org/entity/Q2"},
                            "modelLabel": {"value": "Example Phone"},
                            "brand": {"value": "http://www.wikidata.org/entity/Q1"},
                            "brandLabel": {"value": "Example Brand"},
                        }
                    ]
                }
            }
        )

        rows = fetch_brand_models(client, class_id="Q22645", limit=50)
        csv_rows = list(csv.DictReader(io.StringIO(_brand_model_csv(rows))))

        self.assertEqual(rows, {("Q1", "Example Brand", "Q2", "Example Phone")})
        self.assertEqual(csv_rows[1]["depends_on"], "brand")
        self.assertEqual(csv_rows[1]["parent_value"], "example-brand")
        self.assertEqual(csv_rows[1]["option_value"], "Example Phone")

    def test_breeds_are_converted_to_select_options(self):
        client = MagicMock()
        client.get.return_value = response(
            {
                "results": {
                    "bindings": [
                        {
                            "breed": {"value": "http://www.wikidata.org/entity/Q3"},
                            "breedLabel": {"value": "Example breed"},
                        }
                    ]
                }
            }
        )

        rows = fetch_breeds(client, class_id="Q39367", limit=50)
        csv_rows = list(csv.DictReader(io.StringIO(_breed_csv(rows))))

        self.assertEqual(rows, {("Q3", "Example breed")})
        self.assertEqual(csv_rows[0]["field_key"], "breed_or_type")
        self.assertEqual(csv_rows[0]["option_value"], "example-breed")
