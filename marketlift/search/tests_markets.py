from decimal import Decimal

from django.test import SimpleTestCase

from marketlift.search.parser import parse_marketplace_query


class MultiMarketSearchParserTests(SimpleTestCase):
    def test_ghana_cedi_query(self):
        parsed = parse_marketplace_query("Samsung S24 8GB under GH₵6,000 in Kumasi")
        self.assertEqual(parsed.core_tokens, ("samsung", "s24", "kumasi"))
        self.assertEqual(parsed.specification_tokens, ("8gb",))
        self.assertEqual(parsed.max_price, Decimal("6000"))

    def test_nigeria_naira_million_query(self):
        parsed = parse_marketplace_query("iPhone 15 Pro below ₦1.5m in Lagos")
        self.assertEqual(parsed.core_tokens, ("iphone", "15", "pro", "lagos"))
        self.assertEqual(parsed.max_price, Decimal("1500000.0"))

    def test_kenya_shilling_query(self):
        parsed = parse_marketplace_query("Toyota Axio under KSh 1.8m near Nairobi")
        self.assertEqual(parsed.core_tokens, ("toyota", "axio", "nairobi"))
        self.assertEqual(parsed.max_price, Decimal("1800000.0"))

    def test_south_africa_rand_query(self):
        parsed = parse_marketplace_query("phone under R 25,000 in Cape Town")
        self.assertEqual(parsed.core_tokens, ("phone", "cape", "town"))
        self.assertEqual(parsed.max_price, Decimal("25000"))

    def test_cote_divoire_fcfa_query(self):
        parsed = parse_marketplace_query("iPhone moins de 500000 FCFA à Abidjan")
        self.assertEqual(parsed.core_tokens, ("iphone", "abidjan"))
        self.assertEqual(parsed.max_price, Decimal("500000"))

    def test_inch_unit_still_beats_price_parser(self):
        parsed = parse_marketplace_query("screen under 55 in")
        self.assertIsNone(parsed.max_price)
        constraint = parsed.numeric_specifications[0]
        self.assertEqual(constraint.key, "screen_size")
        self.assertEqual(constraint.maximum, Decimal("55"))
