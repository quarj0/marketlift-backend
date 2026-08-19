import strawberry

from marketlift.graphql.auth import require_staff

from .services import analytics_data, dashboard_data
from .types import (
    AdminAnalyticsType,
    AdminDashboardType,
    DashboardCountsType,
    MarketplaceHealthType,
    MetricType,
    RevenueSummaryType,
    TimeSeriesPointType,
)


def _metrics(rows):
    return [MetricType(label=row["label"], value=row["value"]) for row in rows]


def _series(rows):
    return [TimeSeriesPointType(date=row["date"], value=row["value"]) for row in rows]


@strawberry.type
class AnalyticsQuery:
    @strawberry.field
    def admin_dashboard(self, info: strawberry.Info) -> AdminDashboardType:
        require_staff(info, roles={"admin", "finance", "moderator", "support"})
        data = dashboard_data()
        return AdminDashboardType(
            counts=DashboardCountsType(**data["counts"]),
            revenue=RevenueSummaryType(**data["revenue"]),
        )

    @strawberry.field
    def admin_analytics(
        self, info: strawberry.Info, days: int = 30
    ) -> AdminAnalyticsType:
        require_staff(info, roles={"admin", "finance", "moderator", "support"})
        data = analytics_data(days)
        return AdminAnalyticsType(
            user_growth=_series(data["user_growth"]),
            seller_growth=_series(data["seller_growth"]),
            listing_growth=_series(data["listing_growth"]),
            revenue=_series(data["revenue"]),
            category_distribution=_metrics(data["category_distribution"]),
            plan_distribution=_metrics(data["plan_distribution"]),
            verification_outcomes=_metrics(data["verification_outcomes"]),
            report_outcomes=_metrics(data["report_outcomes"]),
            billing_activity=_metrics(data["billing_activity"]),
            health=MarketplaceHealthType(**data["health"]),
        )
