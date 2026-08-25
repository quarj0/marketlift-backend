from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from marketlift.search.document import build_listing_search_document
from marketlift.search.parser import parse_marketplace_query


class BrazilianMarketplaceQueryMatrixTests(SimpleTestCase):
    @staticmethod
    def _attribute(key, value, *, unit="", label=None):
        return SimpleNamespace(
            key=key,
            label_snapshot=label or key.replace("_", " ").title(),
            value=value,
            field=SimpleNamespace(unit=unit),
        )

    @staticmethod
    def _listing(
        *,
        title,
        description="",
        price,
        condition="Used",
        state="São Paulo",
        state_code="SP",
        city="São Paulo",
        district="Centro",
        category_name="Test",
        category_slug="test",
    ):
        return SimpleNamespace(
            title=title,
            description=description,
            price=Decimal(str(price)),
            condition=condition,
            state=state,
            state_code=state_code,
            country_code="BR",
            city=city,
            district=district,
            category_name=category_name,
            category_slug=category_slug,
        )

    def _assert_query_matches_projection(self, query, listing, attributes):
        parsed = parse_marketplace_query(query)
        doc = build_listing_search_document(listing, attributes)
        tokens = set(doc.tokens)
        missing_core = [token for token in parsed.core_tokens if token not in tokens]
        missing_specs = [
            token for token in parsed.specification_tokens if token not in tokens
        ]
        self.assertEqual(
            missing_core, [], f"Missing core tokens for {query!r}: {missing_core}"
        )
        self.assertEqual(
            missing_specs, [], f"Missing specs for {query!r}: {missing_specs}"
        )
        if parsed.min_price is not None:
            self.assertGreaterEqual(listing.price, parsed.min_price)
        if parsed.max_price is not None:
            self.assertLessEqual(listing.price, parsed.max_price)

    def test_phone_queries_in_english_and_brazilian_portuguese(self):
        listing = self._listing(
            title="Samsung Galaxy S23 256GB",
            price=8500,
            category_name="Mobile Phones",
            category_slug="phones",
        )
        attrs = [
            self._attribute("brand", "samsung", label="Brand"),
            self._attribute("model", "Galaxy S23", label="Model"),
            self._attribute("ram_gb", 8, unit="GB", label="RAM"),
            self._attribute("storage_gb", 256, unit="GB", label="Storage"),
        ]
        for query in (
            "Samsung Galaxy below R$9000 with 8GB RAM at São Paulo",
            "Samsung Galaxy abaixo de R$9.000 com 8GB de RAM em São Paulo",
            "Samsung Galaxy até 9 mil com 8 giga de RAM em São Paulo",
        ):
            with self.subTest(query=query):
                self._assert_query_matches_projection(query, listing, attrs)

    def test_vehicle_query_uses_portuguese_transmission_alias(self):
        listing = self._listing(
            title="Honda Civic 2021",
            price=95000,
            category_name="Vehicles",
            category_slug="vehicles",
        )
        attrs = [
            self._attribute("make", "Honda", label="Make"),
            self._attribute("model", "Civic", label="Model"),
            self._attribute("year", 2021, label="Year"),
            self._attribute("transmission", "automatic", label="Transmission"),
        ]
        self._assert_query_matches_projection(
            "Honda Civic 2021 automático abaixo de R$100 mil em SP", listing, attrs
        )

    def test_computer_query_uses_notebook_and_ram_localization(self):
        listing = self._listing(
            title="Acer Nitro 5 Gamer",
            price=4800,
            category_name="Computers",
            category_slug="computers",
        )
        attrs = [
            self._attribute("device_type", "laptop", label="Device type"),
            self._attribute("ram_gb", 16, unit="GB", label="RAM"),
        ]
        self._assert_query_matches_projection(
            "notebook gamer 16 GB de memória até R$ 5.000,00", listing, attrs
        )

    def test_property_query_uses_portuguese_attribute_aliases(self):
        listing = self._listing(
            title="Imóvel para locação",
            price=2800,
            district="Pinheiros",
            category_name="Properties",
            category_slug="properties",
        )
        attrs = [
            self._attribute("listing_purpose", "rent", label="Listing purpose"),
            self._attribute("property_type", "apartment", label="Property type"),
            self._attribute("bedrooms", 2, label="Bedrooms"),
            self._attribute("furnished", True, label="Furnished"),
        ]
        self._assert_query_matches_projection(
            "apartamento 2 quartos mobiliado até R$3.000 por mês em Pinheiros",
            listing,
            attrs,
        )
