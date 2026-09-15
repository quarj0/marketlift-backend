from django.test import TestCase

from accounts.models import User
from categories.models import Category
from listings.models import Listing
from platform_settings.models import PlatformConfiguration
from reports.models import Report
from sellers.models import SellerProfile

from moderation.models import ModerationCase
from moderation.risk import evaluate_listing_report_risk, listing_report_risk_score


class AutomatedListingFlaggingTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user(email="risk-owner@example.com")
        self.seller = SellerProfile.objects.create(user=owner)
        self.category = Category.objects.create(slug="risk-test", name="Risk test")
        self.listing = Listing.objects.create(
            seller=self.seller,
            category=self.category,
            title="Risk test listing",
            description="Listing used by automated moderation tests.",
            price="100.00",
            city="Sao Paulo",
            status=Listing.Status.PUBLISHED,
        )
        self.reporter_one = User.objects.create_user(email="reporter-one@example.com")
        self.reporter_two = User.objects.create_user(email="reporter-two@example.com")
        config = PlatformConfiguration.load()
        config.automated_listing_flagging = True
        config.high_risk_threshold = 70
        config.save(
            update_fields=(
                "automated_listing_flagging",
                "high_risk_threshold",
                "updated_at",
            )
        )

    def _report(self, reporter, reason=Report.Reason.FRAUD):
        return Report.objects.create(
            reporter=reporter,
            target_type=Report.TargetType.LISTING,
            listing=self.listing,
            target_label_snapshot=self.listing.title,
            reason=reason,
            statement="Risk concern",
        )

    def test_distinct_severe_reports_reach_threshold_and_move_listing_to_review(self):
        self._report(self.reporter_one)
        self._report(self.reporter_two)

        score = evaluate_listing_report_risk(listing_id=self.listing.id)

        self.assertEqual(score, 70)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, Listing.Status.UNDER_REVIEW)
        moderation_case = ModerationCase.objects.get(listing=self.listing)
        self.assertEqual(moderation_case.source, ModerationCase.Source.RISK)
        self.assertIn("risk score 70", moderation_case.review_reason)

    def test_same_reporter_cannot_raise_score_by_submitting_duplicates(self):
        self._report(self.reporter_one)
        self._report(self.reporter_one, reason=Report.Reason.FAKE_LISTING)

        self.assertEqual(listing_report_risk_score(listing_id=self.listing.id), 35)
        evaluate_listing_report_risk(listing_id=self.listing.id)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, Listing.Status.PUBLISHED)

    def test_setting_disables_automatic_moderation(self):
        config = PlatformConfiguration.load()
        config.automated_listing_flagging = False
        config.save(update_fields=("automated_listing_flagging", "updated_at"))
        self._report(self.reporter_one)
        self._report(self.reporter_two)

        self.assertEqual(evaluate_listing_report_risk(listing_id=self.listing.id), 0)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, Listing.Status.PUBLISHED)
