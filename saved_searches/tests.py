from django.test import TestCase
from accounts.models import User
from saved_searches.services import create_saved_search


class SavedSearchTests(TestCase):
    def test_normalizes_criteria(self):
        u = User.objects.create_user(email="s@example.com", password="x", full_name="S")
        x = create_saved_search(
            user=u, name="phones", criteria={"q": "iphone", "evil": 1}
        )
        self.assertEqual(x.criteria, {"q": "iphone"})

    def test_accepts_graphql_style_camel_case_criteria(self):
        u = User.objects.create_user(
            email="camel@example.com", password="x", full_name="C"
        )
        x = create_saved_search(
            user=u,
            name="phones",
            criteria={
                "minPrice": 100,
                "maxPrice": 500,
                "verifiedOnly": True,
                "attributeFilters": {"brand": "Apple"},
            },
        )
        self.assertEqual(
            x.criteria,
            {
                "min_price": 100,
                "max_price": 500,
                "verified_only": True,
                "attribute_filters": {"brand": "Apple"},
            },
        )
