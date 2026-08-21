from decimal import Decimal

from django.test import TransactionTestCase
from django.utils import timezone

from accounts.models import User
from categories.models import Category, CategoryField
from listings.models import Listing, ListingAttribute
from marketlift.search import SearchRequest, search_listings
from marketlift.search.document import rebuild_listing_search_document
from sellers.models import SellerProfile


class MarketplaceSearchIntegrationTests(TransactionTestCase):
    reset_sequences = False

    def setUp(self):
        user = User.objects.create_user(
            email="search-seller@example.com",
            password="SearchPass123!",
            full_name="Search Seller",
        )
        self.seller = SellerProfile.objects.create(
            user=user, display_name="Search Seller"
        )
        self.phones = Category.objects.create(
            slug="phones-search-integration",
            name="Mobile Phones Search Integration",
        )
        self.brand = CategoryField.objects.create(
            category=self.phones,
            key="brand",
            label="Brand",
            field_type=CategoryField.FieldType.TEXT,
            filterable=True,
        )
        self.model = CategoryField.objects.create(
            category=self.phones,
            key="model",
            label="Model",
            field_type=CategoryField.FieldType.TEXT,
            filterable=True,
        )
        self.ram = CategoryField.objects.create(
            category=self.phones,
            key="ram_gb",
            label="RAM",
            field_type=CategoryField.FieldType.NUMBER,
            filterable=True,
            unit="GB",
        )

    def _phone(self, *, title, model, ram, price):
        listing = Listing.objects.create(
            seller=self.seller,
            category=self.phones,
            title=title,
            description="Original smartphone in good condition.",
            price=Decimal(str(price)),
            condition=Listing.Condition.USED,
            state="São Paulo",
            state_code="SP",
            city="São Paulo",
            district="Centro",
            status=Listing.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        ListingAttribute.objects.create(
            listing=listing,
            field=self.brand,
            key="brand",
            label_snapshot="Brand",
            field_type_snapshot="text",
            text_value="samsung",
        )
        ListingAttribute.objects.create(
            listing=listing,
            field=self.model,
            key="model",
            label_snapshot="Model",
            field_type_snapshot="text",
            text_value=model,
        )
        ListingAttribute.objects.create(
            listing=listing,
            field=self.ram,
            key="ram_gb",
            label_snapshot="RAM",
            field_type_snapshot="number",
            number_value=Decimal(str(ram)),
        )
        rebuild_listing_search_document(listing.pk)
        return listing

    def test_typo_and_missing_spec_relax_only_specification(self):
        six = self._phone(
            title="Samsung Galaxy S21 128GB", model="Galaxy S21", ram=6, price=720
        )
        twelve = self._phone(
            title="Samsung Galaxy S21 256GB", model="Galaxy S21", ram=12, price=790
        )
        self._phone(
            title="Samsung Galaxy S22 8GB", model="Galaxy S22", ram=8, price=780
        )

        page = search_listings(
            SearchRequest(q="samsun s21 8gb under r$800", page_size=24)
        )

        self.assertEqual({item.pk for item in page.items}, {six.pk, twelve.pk})
        self.assertEqual([item.value for item in page.relaxed], ["8gb"])
        self.assertEqual(page.parsed_query.max_price, Decimal("800"))

    def test_exact_specification_wins_before_relaxation(self):
        exact = self._phone(
            title="Samsung Galaxy S21 8GB", model="Galaxy S21", ram=8, price=760
        )
        self._phone(
            title="Samsung Galaxy S21 12GB", model="Galaxy S21", ram=12, price=780
        )

        page = search_listings(
            SearchRequest(q="samsung s21 8gb under r$800", page_size=24)
        )

        self.assertEqual([item.pk for item in page.items], [exact.pk])
        self.assertEqual(page.relaxed, [])

    def test_subjective_search_is_not_converted_into_product_advice(self):
        self._phone(title="Samsung Galaxy S21", model="Galaxy S21", ram=8, price=760)
        page = search_listings(
            SearchRequest(q="cheap phone good for gaming", page_size=24)
        )
        self.assertEqual(page.total_count, 0)
        self.assertEqual(page.items, [])

    def test_irrelevant_specification_is_not_relaxed(self):
        vehicles = Category.objects.create(
            slug="vehicles-search-integration",
            name="Vehicles Search Integration",
        )
        year = CategoryField.objects.create(
            category=vehicles,
            key="year",
            label="Year",
            field_type=CategoryField.FieldType.NUMBER,
            filterable=True,
        )
        civic = Listing.objects.create(
            seller=self.seller,
            category=vehicles,
            title="Honda Civic 2020",
            description="Automatic sedan in excellent condition.",
            price=Decimal("78000"),
            condition=Listing.Condition.USED,
            state="São Paulo",
            state_code="SP",
            city="São Paulo",
            district="Centro",
            status=Listing.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        ListingAttribute.objects.create(
            listing=civic,
            field=year,
            key="year",
            label_snapshot="Year",
            field_type_snapshot="number",
            number_value=Decimal("2020"),
        )
        rebuild_listing_search_document(civic.pk)

        page = search_listings(SearchRequest(q="honda civic 8gb", page_size=24))

        self.assertEqual(page.total_count, 0)
        self.assertEqual(page.items, [])
        self.assertEqual(page.relaxed, [])

    def test_location_words_can_match_indexed_listing_location(self):
        housing = Category.objects.create(
            slug="housing-search-integration",
            name="Housing Search Integration",
        )
        room_type = CategoryField.objects.create(
            category=housing,
            key="room_type",
            label="Room Type",
            field_type=CategoryField.FieldType.TEXT,
            filterable=True,
        )
        room = Listing.objects.create(
            seller=self.seller,
            category=housing,
            title="Single Room for Rent",
            description="Clean student accommodation available now.",
            price=Decimal("1200"),
            condition="",
            state="Ashanti",
            state_code="AH",
            city="Kumasi",
            district="KNUST",
            status=Listing.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        ListingAttribute.objects.create(
            listing=room,
            field=room_type,
            key="room_type",
            label_snapshot="Room Type",
            field_type_snapshot="text",
            text_value="single room",
        )
        rebuild_listing_search_document(room.pk)

        page = search_listings(SearchRequest(q="single room at knust", page_size=24))

        self.assertEqual([item.pk for item in page.items], [room.pk])
        self.assertEqual(page.relaxed, [])

    def test_numeric_dynamic_filter_uses_number_storage(self):
        eight = self._phone(
            title="Samsung Galaxy S21 8GB", model="Galaxy S21", ram=8, price=760
        )
        self._phone(
            title="Samsung Galaxy S21 12GB", model="Galaxy S21", ram=12, price=780
        )

        page = search_listings(
            SearchRequest(
                category=self.phones.slug,
                attribute_filters={"ram_gb": 8},
                page_size=24,
            )
        )
        self.assertEqual([item.pk for item in page.items], [eight.pk])

    def test_macro_region_filter_maps_to_brazilian_states(self):
        southeast = self._phone(
            title="Samsung Galaxy S21 São Paulo", model="Galaxy S21", ram=8, price=760
        )
        northeast = Listing.objects.create(
            seller=self.seller,
            category=self.phones,
            title="Samsung Galaxy S21 Salvador",
            description="Original smartphone in good condition.",
            price=Decimal("750"),
            condition=Listing.Condition.USED,
            state="Bahia",
            state_code="BA",
            city="Salvador",
            district="Barra",
            status=Listing.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        rebuild_listing_search_document(northeast.pk)

        page = search_listings(SearchRequest(region="NE", page_size=24))

        self.assertEqual([item.pk for item in page.items], [northeast.pk])
        self.assertNotIn(southeast.pk, {item.pk for item in page.items})
