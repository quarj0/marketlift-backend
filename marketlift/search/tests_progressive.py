from dataclasses import replace
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.contrib.gis.geos import Point
from django.test import TestCase
from accounts.models import User
from categories.models import Category
from listings.models import Listing
from sellers.models import SellerProfile
from .contracts import SearchRequest
from .document import rebuild_listing_search_document
from .progressive import search_progressive


class GeographicSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seller = SellerProfile.objects.create(
            user=User.objects.create_user(email="geo@example.invalid")
        )
        category = Category.objects.create(slug="geo-phones", name="Phones")
        cls.rows = []
        for city, state, district, coordinates in [
            ("São Paulo", "SP", "Centro", (-46.6333, -23.5505)),
            ("São Paulo", "SP", "Pinheiros", (-46.69, -23.56)),
            ("Campinas", "SP", "Centro", (-47.06, -22.90)),
            ("Rio de Janeiro", "RJ", "Centro", (-43.17, -22.91)),
            ("Salvador", "BA", "Centro", (-38.5, -12.98)),
        ]:
            row = Listing.objects.create(
                seller=seller,
                category=category,
                title="Samsung phone",
                price=100,
                status="published",
                country_code="BR",
                state_code=state,
                state=state,
                city=city,
                district=district,
                location_point=Point(*coordinates, srid=4326),
            )
            rebuild_listing_search_document(row.pk)
            cls.rows.append(row)
        other = Listing.objects.create(
            seller=seller,
            category=category,
            title="Apple phone",
            price=100,
            status="published",
            country_code="BR",
            state_code="BA",
            city="Salvador",
        )
        rebuild_listing_search_document(other.pk)

    def collect(self, request):
        ids, areas = [], []
        for _ in range(20):
            page, area = search_progressive(request)
            ids += [row.pk for row in page.items]
            areas.append(area)
            if not page.next_cursor:
                break
            request = replace(request, cursor=page.next_cursor)
        else:
            self.fail("Continuation did not terminate")
        return ids, areas

    def test_local_first_disjoint_pages_preserve_product_filters(self):
        ids, areas = self.collect(
            SearchRequest(
                q="samsung",
                state="SP",
                city="São Paulo",
                district="Centro",
                page_size=1,
            )
        )
        self.assertEqual(ids, [row.pk for row in self.rows])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(areas[0]["expanded"])
        self.assertTrue(areas[-1]["expanded"])

    def test_distance_rings_are_disjoint(self):
        ids, areas = self.collect(
            SearchRequest(
                q="samsung",
                latitude=-23.5505,
                longitude=-46.6333,
                radius_km=25,
                state="SP",
                city="São Paulo",
                sort="distance",
                page_size=1,
            )
        )
        self.assertEqual(ids, [row.pk for row in self.rows])
        self.assertGreater(len(areas), 1)

    def test_empty_locality_continues_and_reports_expansion(self):
        page, area = search_progressive(
            SearchRequest(q="samsung", state="SP", city="Missing city")
        )
        self.assertTrue(page.items)
        self.assertTrue(area["expanded"])
        self.assertEqual(area["origin"], "Missing city")

    def test_cursor_cannot_change_filters_or_be_tampered(self):
        request = SearchRequest(q="samsung", state="SP", page_size=1)
        page, _ = search_progressive(request)
        for changed in [
            replace(request, min_price=Decimal("50"), cursor=page.next_cursor),
            replace(request, cursor="tampered"),
        ]:
            with self.assertRaises(ValidationError):
                search_progressive(changed)
