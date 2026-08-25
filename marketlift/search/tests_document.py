from types import SimpleNamespace

from django.test import SimpleTestCase

from marketlift.search.document import build_listing_search_document


class SearchDocumentLocalizationTests(SimpleTestCase):
    def _listing(self, *, condition="Used"):
        return SimpleNamespace(
            title="Produto",
            description="",
            category_name="Test",
            category_slug="test",
            country_code="BR",
            state="São Paulo",
            state_code="SP",
            city="São Paulo",
            district="Centro",
            condition=condition,
        )

    @staticmethod
    def _attribute(key, value, *, unit=""):
        field = SimpleNamespace(unit=unit)
        return SimpleNamespace(
            key=key,
            label_snapshot=key.replace("_", " ").title(),
            value=value,
            field=field,
        )

    def test_used_condition_indexes_portuguese_alias(self):
        doc = build_listing_search_document(self._listing(condition="Used"), [])
        self.assertIn("usado", doc.tokens)
        self.assertIn("usada", doc.tokens)

    def test_vehicle_automatic_indexes_portuguese_alias(self):
        doc = build_listing_search_document(
            self._listing(), [self._attribute("transmission", "automatic")]
        )
        self.assertIn("automatico", doc.tokens)
        self.assertIn("automatica", doc.tokens)

    def test_property_attributes_index_portuguese_search_phrases(self):
        attrs = [
            self._attribute("property_type", "apartment"),
            self._attribute("bedrooms", 2),
            self._attribute("furnished", True),
        ]
        doc = build_listing_search_document(self._listing(), attrs)
        self.assertIn("apartamento", doc.tokens)
        self.assertIn("quartos", doc.tokens)
        self.assertIn("mobiliado", doc.tokens)

    def test_laptop_indexes_notebook_alias(self):
        doc = build_listing_search_document(
            self._listing(), [self._attribute("device_type", "laptop")]
        )
        self.assertIn("notebook", doc.tokens)
