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

    def test_portuguese_thousand_shorthand_and_giga_are_understood(self):
        parsed = parse_marketplace_query(
            "Samsung Galaxy até 9 mil com 8 giga de RAM em São Paulo"
        )
        self.assertEqual(parsed.core_tokens, ("samsung", "galaxy", "sao", "paulo"))
        self.assertEqual(parsed.specification_tokens, ("8gb",))
        self.assertEqual(parsed.max_price, Decimal("9000"))

    def test_currency_k_shorthand_is_understood(self):
        parsed = parse_marketplace_query("Samsung Galaxy por até R$ 9k 8GB RAM")
        self.assertEqual(parsed.core_tokens, ("samsung", "galaxy"))
        self.assertEqual(parsed.specification_tokens, ("8gb",))
        self.assertEqual(parsed.max_price, Decimal("9000"))

    def test_decimal_thousand_shorthand_is_understood(self):
        parsed = parse_marketplace_query("iphone abaixo de R$1,5 mil")
        self.assertEqual(parsed.max_price, Decimal("1500.0"))

    def test_million_shorthand_is_understood(self):
        parsed = parse_marketplace_query("casa até R$1,2 milhão")
        self.assertEqual(parsed.max_price, Decimal("1200000.0"))

    def test_portuguese_at_least_is_understood(self):
        parsed = parse_marketplace_query("iphone pelo menos R$3.000")
        self.assertEqual(parsed.core_tokens, ("iphone",))
        self.assertEqual(parsed.min_price, Decimal("3000"))

    def test_bare_starting_year_is_not_misread_as_price(self):
        parsed = parse_marketplace_query(
            "Toyota Corolla a partir de 2020 até R$120.000 em Campinas"
        )
        self.assertEqual(parsed.core_tokens, ("toyota", "corolla", "campinas"))
        self.assertIsNone(parsed.min_price)
        self.assertEqual(parsed.max_price, Decimal("120000"))
        self.assertEqual(len(parsed.numeric_specifications), 1)
        year = parsed.numeric_specifications[0]
        self.assertEqual(year.key, "year")
        self.assertEqual(year.minimum, Decimal("2020"))
        self.assertIsNone(year.maximum)

    def test_explicit_starting_price_still_works(self):
        parsed = parse_marketplace_query("iphone a partir de R$3.000")
        self.assertEqual(parsed.min_price, Decimal("3000"))

    def test_liters_are_normalized_as_product_specification(self):
        parsed = parse_marketplace_query("geladeira 400 litros até R$3 mil")
        self.assertEqual(parsed.core_tokens, ("geladeira",))
        self.assertEqual(parsed.specification_tokens, ("400l",))
        self.assertEqual(parsed.max_price, Decimal("3000"))

    def test_relative_radius_is_not_product_specification(self):
        parsed = parse_marketplace_query("iPhone 15 Pro within 20km of me")
        self.assertEqual(parsed.core_tokens, ("iphone", "15", "pro"))
        self.assertEqual(parsed.specification_tokens, ())
        self.assertEqual(parsed.radius_km, Decimal("20"))
        self.assertTrue(parsed.near_me)

    def test_portuguese_near_me_is_removed_from_text_anchor(self):
        parsed = parse_marketplace_query("iPhone 15 Pro perto de mim")
        self.assertEqual(parsed.core_tokens, ("iphone", "15", "pro"))
        self.assertTrue(parsed.near_me)
        self.assertIsNone(parsed.radius_km)

    def test_portuguese_radius_phrase_supports_decimal_comma(self):
        parsed = parse_marketplace_query("iPhone em um raio de 12,5 km")
        self.assertEqual(parsed.core_tokens, ("iphone",))
        self.assertEqual(parsed.radius_km, Decimal("12.5"))
        self.assertTrue(parsed.near_me)

    def test_month_is_grammar_not_required_search_term(self):
        parsed = parse_marketplace_query(
            "apartamento 2 quartos mobiliado até R$3.000 por mês em Pinheiros"
        )
        self.assertEqual(
            parsed.core_tokens,
            ("apartamento", "2", "quartos", "mobiliado", "pinheiros"),
        )
        self.assertEqual(parsed.max_price, Decimal("3000"))

    def test_ram_floor_becomes_numeric_attribute_range(self):
        parsed = parse_marketplace_query("notebook pelo menos 16gb ram")
        self.assertEqual(parsed.core_tokens, ("notebook",))
        self.assertEqual(parsed.specification_tokens, ())
        constraint = parsed.numeric_specifications[0]
        self.assertEqual(constraint.key, "ram_gb")
        self.assertEqual(constraint.unit, "gb")
        self.assertEqual(constraint.minimum, Decimal("16"))
        self.assertIsNone(constraint.maximum)

    def test_storage_ceiling_becomes_numeric_attribute_range(self):
        parsed = parse_marketplace_query("iphone até 256gb storage")
        constraint = parsed.numeric_specifications[0]
        self.assertEqual(constraint.key, "storage_gb")
        self.assertEqual(constraint.maximum, Decimal("256"))

    def test_mileage_ceiling_is_not_misread_as_price(self):
        parsed = parse_marketplace_query("Honda Civic menos de 100 mil km")
        self.assertIsNone(parsed.max_price)
        self.assertEqual(parsed.specification_tokens, ())
        constraint = parsed.numeric_specifications[0]
        self.assertEqual(constraint.key, "mileage_km")
        self.assertEqual(constraint.maximum, Decimal("100000"))

    def test_brazilian_dot_thousands_work_for_mileage(self):
        parsed = parse_marketplace_query("Honda Civic abaixo de 100.000 km")
        constraint = parsed.numeric_specifications[0]
        self.assertEqual(constraint.maximum, Decimal("100000"))

    def test_area_floor_becomes_generic_m2_range(self):
        parsed = parse_marketplace_query("casa acima de 100 m²")
        constraint = parsed.numeric_specifications[0]
        self.assertIsNone(constraint.key)
        self.assertEqual(constraint.unit, "m2")
        self.assertEqual(constraint.minimum, Decimal("100"))

    def test_after_year_becomes_exclusive_year_floor(self):
        parsed = parse_marketplace_query("Toyota Corolla after 2020 under R$120k")
        self.assertEqual(parsed.core_tokens, ("toyota", "corolla"))
        self.assertEqual(parsed.max_price, Decimal("120000"))
        constraint = parsed.numeric_specifications[0]
        self.assertEqual(constraint.key, "year")
        self.assertEqual(constraint.minimum, Decimal("2021"))

    def test_before_year_becomes_exclusive_year_ceiling(self):
        parsed = parse_marketplace_query("Civic before 2020")
        constraint = parsed.numeric_specifications[0]
        self.assertEqual(constraint.key, "year")
        self.assertEqual(constraint.maximum, Decimal("2019"))

    def test_currency_suffix_disambiguates_starting_value_from_year(self):
        parsed = parse_marketplace_query("iphone a partir de 2020 reais")
        self.assertEqual(parsed.min_price, Decimal("2020"))
        self.assertEqual(parsed.numeric_specifications, ())

    def test_percent_specification_is_not_lost_at_end_of_query(self):
        parsed = parse_marketplace_query("iphone battery 90%")
        self.assertEqual(parsed.specification_tokens, ("90%",))
        self.assertIsNone(parsed.max_price)

    def test_battery_floor_is_numeric_specification_not_price(self):
        parsed = parse_marketplace_query("iphone acima de 80% bateria")
        self.assertIsNone(parsed.min_price)
        constraint = parsed.numeric_specifications[0]
        self.assertEqual(constraint.key, "battery_health")
        self.assertEqual(constraint.minimum, Decimal("80"))
