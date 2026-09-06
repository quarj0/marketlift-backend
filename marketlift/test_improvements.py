from types import SimpleNamespace
from unittest.mock import patch
from django.core.cache import cache
from django.test import TestCase, SimpleTestCase, override_settings
from django.http import JsonResponse
from django.test import RequestFactory
from django.contrib.gis.geos import Point
from rest_framework.test import APIRequestFactory
from accounts.models import User
from categories.models import Category
from sellers.models import SellerProfile
from listings.models import Listing
from marketlift.graphql.admin_pages import AdminPaginationQuery
from marketlift.graphql.schema import schema
from marketlift.security.middleware import SecurityRateLimitMiddleware
from marketlift.security.rate_limit import (
    RateLimitUnavailable,
    enforce_identity_rate_limit,
)
from marketlift.api.sitemaps import SitemapView
from accounts.export import export_sources
from marketlift.api.telemetry import WebVitalsView
from messaging.models import Conversation, Message
from messaging.graphql.queries import MessagingQuery
from moderation.models import ModerationCase
from reports.models import Report
from django.utils import timezone


class AdminPagingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(
            email="admin-page@example.invalid", is_staff=True, admin_role="admin"
        )
        User.objects.bulk_create(
            [
                User(email=f"page{i}@example.invalid", full_name=f"Customer {i:03d}")
                for i in range(250)
            ]
        )

    def test_all_records_accessible_with_matching_total_and_search(self):
        info = SimpleNamespace(context=SimpleNamespace(user=self.staff))
        query = AdminPaginationQuery()
        page = query.admin_record_page(
            info, area="users", q="Customer", limit=25, offset=225
        )
        self.assertEqual(page.total_count, 250)
        self.assertEqual(len(page.admin_users), 25)
        filtered = query.admin_record_page(info, area="users", q="Customer 249")
        self.assertEqual(filtered.total_count, 1)
        self.assertEqual(filtered.admin_users[0].name, "Customer 249")

    def test_graphql_contract_and_area_permission(self):
        query = 'query { adminRecordPage(area:"users",limit:5) { totalCount adminUsers { id name } } }'
        result = schema.execute_sync(
            query, context_value=SimpleNamespace(user=self.staff)
        )
        self.assertIsNone(result.errors)
        self.assertEqual(len(result.data["adminRecordPage"]["adminUsers"]), 5)
        self.staff.admin_role = "finance"
        denied = schema.execute_sync(
            query, context_value=SimpleNamespace(user=self.staff)
        )
        self.assertTrue(denied.errors)


class SitemapAndExportTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user(email="owner@example.invalid")
        self.other = User.objects.create_user(email="other@example.invalid")
        self.seller = SellerProfile.objects.create(user=self.owner)
        self.category = Category.objects.create(slug="sitemap-test", name="Test")
        self.rows = [
            Listing.objects.create(
                seller=self.seller,
                category=self.category,
                title=f"Phone {i}",
                price=10,
                status="published",
                location_point=Point(-46.63, -23.55),
            )
            for i in range(55)
        ]
        Listing.objects.create(
            seller=self.seller,
            category=self.category,
            title="Private draft",
            price=10,
            status="draft",
        )

    def test_sitemap_partitions_cover_more_than_fifty_and_hide_drafts(self):
        view = SitemapView.as_view()
        factory = APIRequestFactory()
        index = view(factory.get("/api/v1/sitemap/")).data
        slugs = []
        for partition in index["partitions"]:
            response = view(
                factory.get("/api/v1/sitemap/", {"bucket": partition["bucket"]})
            )
            slugs.extend(item["slug"] for item in response.data["listings"])
        self.assertEqual(set(slugs), {row.slug for row in self.rows})

    def test_deactivation_hides_public_inventory_and_export_is_owned(self):
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])
        self.assertFalse(Listing.objects.public().exists())
        sources = dict(export_sources(self.other.pk))
        self.assertFalse(sources["listing"].exists())
        self.assertEqual(sources["profile"].get()["email"], self.other.email)
        self.assertNotIn("password", sources["profile"].get())

    def test_every_export_source_executes_and_private_support_notes_are_excluded(self):
        from support.models import SupportTicket, SupportMessage

        ticket = SupportTicket.objects.create(
            user=self.owner, subject="My data", category="account"
        )
        SupportMessage.objects.create(
            ticket=ticket, sender=self.owner, body="Public reply"
        )
        SupportMessage.objects.create(
            ticket=ticket, sender=self.other, body="Staff only", internal=True
        )
        sources = {kind: list(query) for kind, query in export_sources(self.owner.pk)}
        self.assertEqual(
            [row["body"] for row in sources["support_message"]], ["Public reply"]
        )
        self.assertEqual(len(sources["listing"]), 56)

    def test_invalid_sitemap_country_returns_client_error(self):
        response = SitemapView.as_view()(
            APIRequestFactory().get("/api/v1/sitemap/", {"countryCode": "ZZ"})
        )
        self.assertEqual(response.status_code, 400)

    def test_pending_seller_filter_matches_unverified_ui_status_and_includes_owner(
        self,
    ):
        self.owner.is_staff = True
        self.owner.admin_role = "admin"
        info = SimpleNamespace(context=SimpleNamespace(user=self.owner))
        page = AdminPaginationQuery().admin_record_page(
            info, area="sellers", status="pending"
        )
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.admin_sellers[0].owner_name, self.owner.email)
        self.assertTrue(page.admin_sellers[0].plan_name)

    def test_deployment_diagnostics_reports_real_schema_and_backlogs(self):
        import io
        import json
        from django.core.management import call_command

        output = io.StringIO()
        call_command("deployment_diagnostics", stdout=output)
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(rows[1]["pendingMigrations"], [])
        self.assertEqual(rows[1]["status"], "ok")
        self.assertEqual(rows[2]["notificationDelivery"]["exhausted"], 0)
        self.assertEqual(rows[2]["uploadProcessing"]["failed"], 0)

    def test_listing_detail_loads_context_and_preserves_support_role_boundary(self):
        listing = self.rows[0]
        listing.status = "under_review"
        listing.save(update_fields=["status"])
        report = Report.objects.create(
            reporter=self.other,
            listing=listing,
            target_type="listing",
            reason="other",
            statement="Issue",
            internal_note="Moderator only",
        )
        ModerationCase.objects.create(listing=listing, review_reason="Review listing")
        self.owner.is_staff = True
        self.owner.admin_role = "admin"
        info = SimpleNamespace(context=SimpleNamespace(user=self.owner))
        query = AdminPaginationQuery()
        page = query.admin_record_page(info, area="listings", record_id=str(listing.pk))
        self.assertEqual(page.admin_listings[0].report_count, 1)
        self.assertEqual(str(page.reports[0].id), str(report.pk))
        self.assertEqual(len(page.moderation_queue), 1)
        self.assertEqual(
            query.admin_record_page(info, area="listings", status="review").total_count,
            1,
        )
        self.assertEqual(
            query.admin_record_page(
                info, area="reports", q=str(listing.pk)
            ).total_count,
            1,
        )
        self.owner.admin_role = "support"
        support_page = query.admin_record_page(
            info, area="listings", record_id=str(listing.pk)
        )
        self.assertEqual(support_page.reports, [])
        self.assertEqual(support_page.moderation_queue, [])


class MessagePagingTests(TestCase):
    def test_equal_timestamp_history_has_no_gaps_and_other_users_cannot_read_it(self):
        seller = SellerProfile.objects.create(
            user=User.objects.create_user(email="history-seller@example.invalid")
        )
        buyer = User.objects.create_user(email="history-buyer@example.invalid")
        outsider = User.objects.create_user(email="history-outsider@example.invalid")
        conversation = Conversation.objects.create(
            seller=seller, buyer=buyer, listing_title_snapshot="Phone"
        )
        messages = Message.objects.bulk_create(
            [
                Message(conversation=conversation, sender=buyer, text=str(i))
                for i in range(105)
            ]
        )
        boundary = timezone.now()
        Message.objects.filter(conversation=conversation).update(created_at=boundary)
        info = SimpleNamespace(context=SimpleNamespace(user=buyer))
        query = MessagingQuery()
        seen = []
        before = before_id = None
        for _ in range(3):
            page = query.messages(
                info,
                conversation_id=str(conversation.pk),
                before=before,
                before_id=before_id,
                limit=50,
            )
            seen.extend(str(row.id) for row in page)
            before, before_id = boundary, page[0].id
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(set(seen), {str(row.pk) for row in messages})
        denied = schema.execute_sync(
            "query($id: ID!) { messages(conversationId:$id) { id } }",
            variable_values={"id": str(conversation.pk)},
            context_value=SimpleNamespace(user=outsider),
        )
        self.assertTrue(denied.errors)


class RequestBudgetTests(SimpleTestCase):
    def test_invalid_metric_shapes_and_nonfinite_values_are_rejected(self):
        cache.clear()
        for payload in [
            [],
            {"name": [], "route": "/", "value": 1},
            {"name": "CLS", "route": "/", "value": "NaN"},
        ]:
            response = WebVitalsView.as_view()(
                APIRequestFactory().post(
                    "/api/v1/telemetry/web-vitals/", payload, format="json"
                )
            )
            self.assertEqual(response.status_code, 400)

    @override_settings(MARKETLIFT_GRAPHQL_READ_RATE_LIMIT_PER_MINUTE=2)
    def test_graphql_read_budget_is_separate_and_applies_to_get(self):
        cache.clear()
        middleware = SecurityRateLimitMiddleware(
            lambda request: JsonResponse({"ok": True})
        )
        responses = [
            middleware(RequestFactory().get("/graphql/", {"query": "{health{status}}"}))
            for _ in range(3)
        ]
        self.assertEqual([row.status_code for row in responses], [200, 200, 429])
        self.assertEqual(responses[-1]["Retry-After"], "60")

    @override_settings(MARKETLIFT_RATE_LIMIT_FAIL_CLOSED=True)
    def test_cache_outage_does_not_remove_protection(self):
        with patch(
            "marketlift.security.rate_limit.cache.add", side_effect=ConnectionError
        ):
            with self.assertRaises(RateLimitUnavailable):
                enforce_identity_rate_limit("auth-login", "example", limit=1, window=60)
