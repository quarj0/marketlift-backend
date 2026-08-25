from decimal import Decimal

from django.test import SimpleTestCase

from marketlift.search.backends.postgres import _apply_structured_filters
from marketlift.search.contracts import (
    NumericSpecificationConstraint,
    ParsedMarketplaceQuery,
    SearchRequest,
)


class _FakeQuerySet:
    def __init__(self):
        self.filters = []

    def filter(self, *args, **kwargs):
        self.filters.append((args, kwargs))
        return self

    def exclude(self, *args, **kwargs):
        return self

    def annotate(self, *args, **kwargs):
        return self

    def distinct(self):
        return self


class NumericSpecificationBackendTests(SimpleTestCase):
    def test_keyed_ram_range_uses_numeric_attribute_storage(self):
        qs = _FakeQuerySet()
        parsed = ParsedMarketplaceQuery(
            original="at least 16gb ram",
            normalized="at least 16gb ram",
            numeric_specifications=(
                NumericSpecificationConstraint(
                    unit="gb", key="ram_gb", minimum=Decimal("16")
                ),
            ),
        )
        _apply_structured_filters(qs, SearchRequest(), parsed)
        _, kwargs = qs.filters[-1]
        self.assertEqual(kwargs["attribute_values__key"], "ram_gb")
        self.assertEqual(kwargs["attribute_values__number_value__gte"], Decimal("16"))

    def test_year_range_does_not_require_a_unit(self):
        qs = _FakeQuerySet()
        parsed = ParsedMarketplaceQuery(
            original="after 2020",
            normalized="after 2020",
            numeric_specifications=(
                NumericSpecificationConstraint(key="year", minimum=Decimal("2021")),
            ),
        )
        _apply_structured_filters(qs, SearchRequest(), parsed)
        args, kwargs = qs.filters[-1]
        self.assertEqual(args, ())
        self.assertEqual(kwargs["attribute_values__key"], "year")
        self.assertEqual(kwargs["attribute_values__number_value__gte"], Decimal("2021"))

    def test_generic_area_range_keeps_unit_family_filter(self):
        qs = _FakeQuerySet()
        parsed = ParsedMarketplaceQuery(
            original="above 100m2",
            normalized="above 100m2",
            numeric_specifications=(
                NumericSpecificationConstraint(unit="m2", minimum=Decimal("100")),
            ),
        )
        _apply_structured_filters(qs, SearchRequest(), parsed)
        args, kwargs = qs.filters[-1]
        self.assertEqual(len(args), 1)
        self.assertEqual(kwargs["attribute_values__number_value__gte"], Decimal("100"))
