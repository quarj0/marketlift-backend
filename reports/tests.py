from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from reports.models import Report
from reports.services import create_report, dismiss_report, resolve_report

User = get_user_model()


class ReportDecisionTests(TestCase):
    def setUp(self):
        self.reporter = User.objects.create_user(
            email="reporter@example.com", password="pass", full_name="Reporter"
        )
        self.target = User.objects.create_user(
            email="target@example.com", password="pass", full_name="Target"
        )
        self.admin = User.objects.create_user(
            email="admin2@example.com",
            password="pass",
            full_name="Admin",
            is_staff=True,
        )

    def test_resolve_cannot_be_dismissed_later(self):
        report = create_report(
            reporter=self.reporter,
            target_type="user",
            target_id=self.target.id,
            reason="account",
            statement="problem",
        )
        resolve_report(report=report, actor=self.admin, reason="handled")
        with self.assertRaises(ValidationError):
            dismiss_report(report=report, actor=self.admin, reason="no")

    def test_marketplace_report_reasons_are_preserved(self):
        for reason in ("fake_listing", "incorrect_info", "unavailable"):
            report = create_report(
                reporter=self.reporter,
                target_type="user",
                target_id=self.target.id,
                reason=reason,
                statement="Marketplace report details",
            )
            self.assertEqual(report.reason, reason)

    def test_optional_report_details_fall_back_to_reason_label(self):
        report = create_report(
            reporter=self.reporter,
            target_type="user",
            target_id=self.target.id,
            reason="fake_listing",
            statement="",
        )

        self.assertEqual(report.statement, "Fake listing")
