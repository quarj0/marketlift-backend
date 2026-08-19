from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from accounts.models import User
from listings.models import Listing
from payments.models import Payment
from reports.models import Report
from sellers.models import SellerProfile
from subscriptions.models import SellerSubscription
from support.models import SupportTicket
from verifications.models import VerificationSubmission


def _money(value):
    return float(value or Decimal("0"))


def dashboard_data():
    now = timezone.now()
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    paid = Payment.objects.filter(status=Payment.Status.PAID)

    counts = {
        "total_users": User.objects.count(),
        "total_sellers": SellerProfile.objects.count(),
        "active_sellers": SellerProfile.objects.filter(is_suspended=False).count(),
        "verified_sellers": SellerProfile.objects.filter(
            verified_at__isnull=False
        ).count(),
        "total_listings": Listing.objects.count(),
        "published_listings": Listing.objects.filter(
            status=Listing.Status.PUBLISHED
        ).count(),
        "listings_under_review": Listing.objects.filter(
            status=Listing.Status.UNDER_REVIEW
        ).count(),
        "rejected_listings": Listing.objects.filter(
            status=Listing.Status.REJECTED
        ).count(),
        "reported_listings": Listing.objects.filter(
            reports__status__in=[Report.Status.OPEN, Report.Status.REVIEW]
        )
        .distinct()
        .count(),
        "open_reports": Report.objects.filter(
            status__in=[Report.Status.OPEN, Report.Status.REVIEW]
        ).count(),
        "pending_verifications": VerificationSubmission.objects.filter(
            status__in=[
                VerificationSubmission.Status.PENDING,
                VerificationSubmission.Status.REVIEW,
            ]
        ).count(),
        "failed_payments": Payment.objects.filter(status=Payment.Status.FAILED).count(),
        "recorded_payments": Payment.objects.count(),
        "open_support_tickets": SupportTicket.objects.filter(
            status__in=[SupportTicket.Status.OPEN, SupportTicket.Status.REVIEW]
        ).count(),
        "paid_subscriptions": SellerSubscription.objects.filter(
            status=SellerSubscription.Status.ACTIVE,
            plan__monthly_price__gt=0,
        ).count(),
    }

    revenue = {
        "today": _money(
            paid.filter(paid_at__gte=today).aggregate(x=Sum("amount"))["x"]
        ),
        "this_month": _money(
            paid.filter(paid_at__gte=month).aggregate(x=Sum("amount"))["x"]
        ),
        "total": _money(paid.aggregate(x=Sum("amount"))["x"]),
        "subscription_total": _money(
            paid.filter(purpose=Payment.Purpose.SUBSCRIPTION).aggregate(
                x=Sum("amount")
            )["x"]
        ),
        "promotion_total": _money(
            paid.filter(purpose=Payment.Purpose.PROMOTION).aggregate(x=Sum("amount"))[
                "x"
            ]
        ),
    }
    return {"counts": counts, "revenue": revenue}


def _series(queryset, field, days, *, amount=False):
    start = timezone.now() - timedelta(days=days)
    queryset = (
        queryset.filter(**{f"{field}__gte": start})
        .annotate(day=TruncDate(field))
        .values("day")
        .annotate(value=Sum("amount") if amount else Count("id"))
        .order_by("day")
    )
    return [{"date": row["day"], "value": float(row["value"] or 0)} for row in queryset]


def analytics_data(days=30):
    days = max(1, min(days, 366))
    paid = Payment.objects.filter(status=Payment.Status.PAID)

    total_listings = max(Listing.objects.count(), 1)
    published_listings = Listing.objects.filter(status=Listing.Status.PUBLISHED).count()
    total_sellers = max(SellerProfile.objects.count(), 1)
    active_sellers = SellerProfile.objects.filter(is_suspended=False).count()
    open_reports = Report.objects.filter(
        status__in=[Report.Status.OPEN, Report.Status.REVIEW]
    ).count()
    total_payments = Payment.objects.count()
    paid_payments = Payment.objects.filter(status=Payment.Status.PAID).count()

    billing_activity = [
        {
            "label": "Seller subscriptions",
            "value": float(
                Payment.objects.filter(purpose=Payment.Purpose.SUBSCRIPTION).count()
            ),
        }
    ]
    billing_activity.extend(
        {
            "label": row["promotion_product__name"] or "Promotion",
            "value": float(row["value"]),
        }
        for row in Payment.objects.filter(purpose=Payment.Purpose.PROMOTION)
        .values("promotion_product__name")
        .annotate(value=Count("id"))
        .order_by("-value")[:10]
    )

    return {
        "user_growth": _series(User.objects.all(), "date_joined", days),
        "seller_growth": _series(SellerProfile.objects.all(), "activated_at", days),
        "listing_growth": _series(Listing.objects.all(), "created_at", days),
        "revenue": _series(paid, "paid_at", days, amount=True),
        "category_distribution": [
            {
                "label": row["category_name_snapshot"] or "Unknown",
                "value": float(row["value"]),
            }
            for row in Listing.objects.values("category_name_snapshot")
            .annotate(value=Count("id"))
            .order_by("-value")[:20]
        ],
        "plan_distribution": [
            {"label": row["plan__name"], "value": float(row["value"])}
            for row in SellerSubscription.objects.filter(
                status=SellerSubscription.Status.ACTIVE
            )
            .values("plan__name")
            .annotate(value=Count("id"))
            .order_by("-value")
        ],
        "verification_outcomes": [
            {"label": row["status"], "value": float(row["value"])}
            for row in VerificationSubmission.objects.values("status").annotate(
                value=Count("id")
            )
        ],
        "report_outcomes": [
            {"label": row["status"], "value": float(row["value"])}
            for row in Report.objects.values("status").annotate(value=Count("id"))
        ],
        "billing_activity": billing_activity,
        "health": {
            "payment_success_percent": (
                round((paid_payments / total_payments) * 100, 1)
                if total_payments
                else 100.0
            ),
            "open_report_rate_percent": round((open_reports / total_listings) * 100, 1),
            "active_listing_percent": round(
                (published_listings / total_listings) * 100, 1
            ),
            "active_seller_percent": round((active_sellers / total_sellers) * 100, 1),
        },
    }
