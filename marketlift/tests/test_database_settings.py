from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from marketlift.settings import database_config


class DatabaseSettingsTests(SimpleTestCase):
    def test_development_uses_local_postgis_fallback(self):
        config = database_config("", is_production=False)

        self.assertEqual(config["ENGINE"], "django.contrib.gis.db.backends.postgis")
        self.assertEqual(config["HOST"], "127.0.0.1")
        self.assertEqual(config["PORT"], 5433)
        self.assertEqual(config["NAME"], "marketlift")
        self.assertEqual(config["USER"], "marketlift")
        self.assertEqual(config["PASSWORD"], "marketlift")

    def test_production_parses_neon_style_url_and_preserves_options(self):
        config = database_config(
            "postgresql://ep.example.neon.tech/marketlift"
            "?sslmode=verify-full&channel_binding=require",
            is_production=True,
        )

        self.assertEqual(config["ENGINE"], "django.contrib.gis.db.backends.postgis")
        self.assertEqual(config["HOST"], "ep.example.neon.tech")
        self.assertEqual(config["OPTIONS"]["sslmode"], "verify-full")
        self.assertEqual(config["OPTIONS"]["channel_binding"], "require")
        self.assertEqual(config["CONN_MAX_AGE"], 60)
        self.assertTrue(config["CONN_HEALTH_CHECKS"])

    def test_production_requires_database_url(self):
        with self.assertRaisesMessage(
            ImproperlyConfigured, "DATABASE_URL is required in production."
        ):
            database_config("", is_production=True)
