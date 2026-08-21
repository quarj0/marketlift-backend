from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from marketlift.search.parser import parse_marketplace_query


class MarketplaceSearchParserTests(SimpleTestCase):
    def test_english_product_query_extracts_price_and_spec(self):
        parsed = parse_marketplace_query("samsun s21 8gb under r$800")
        self.assertEqual(parsed.core_tokens, ("samsun", "s21"))
        self.assertEqual(parsed.specification_tokens, ("8gb",))
        self.assertEqual(parsed.max_price, Decimal("800"))
        self.assertIsNone(parsed.min_price)

    def test_portuguese_price_and_spaced_unit(self):
        parsed = parse_marketplace_query("Samsung S21 8 GB até R$ 1.200")
        self.assertEqual(parsed.core_tokens, ("samsung", "s21"))
        self.assertEqual(parsed.specification_tokens, ("8gb",))
        self.assertEqual(parsed.max_price, Decimal("1200"))

    def test_location_query_only_removes_grammar_words(self):
        parsed = parse_marketplace_query("single room at knust")
        self.assertEqual(parsed.core_tokens, ("single", "room", "knust"))
        self.assertEqual(parsed.specification_tokens, ())

    def test_subjective_query_is_not_interpreted_semantically(self):
        parsed = parse_marketplace_query("cheap phone good for gaming")
        self.assertEqual(parsed.core_tokens, ("cheap", "phone", "good", "gaming"))
        self.assertIsNone(parsed.min_price)
        self.assertIsNone(parsed.max_price)
        self.assertEqual(parsed.specification_tokens, ())

    def test_price_range(self):
        parsed = parse_marketplace_query("iphone entre R$ 700 e R$ 900")
        self.assertEqual(parsed.core_tokens, ("iphone",))
        self.assertEqual(parsed.min_price, Decimal("700"))
        self.assertEqual(parsed.max_price, Decimal("900"))

    def test_reversed_price_range_rejected(self):
        with self.assertRaises(ValidationError):
            parse_marketplace_query("iphone between 900 and 700")

    def test_specification_only_query_has_no_text_anchor(self):
        parsed = parse_marketplace_query("8gb")
        self.assertFalse(parsed.has_text_anchor)
        self.assertEqual(parsed.specification_tokens, ("8gb",))
