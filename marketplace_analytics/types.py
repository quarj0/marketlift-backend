from datetime import date

import strawberry


@strawberry.type
class MetricType:
    label: str
    value: float


@strawberry.type
class TimeSeriesPointType:
    date: date
    value: float


@strawberry.type
class DashboardCountsType:
    total_users: int
    total_sellers: int
    active_sellers: int
    verified_sellers: int
    total_listings: int
    published_listings: int
    listings_under_review: int
    rejected_listings: int
    reported_listings: int
    open_reports: int
    pending_verifications: int
    failed_payments: int
    recorded_payments: int
    open_support_tickets: int
    paid_subscriptions: int


@strawberry.type
class RevenueSummaryType:
    today: float
    this_month: float
    total: float
    subscription_total: float
    promotion_total: float


@strawberry.type
class AdminDashboardType:
    counts: DashboardCountsType
    revenue: RevenueSummaryType


@strawberry.type
class MarketplaceHealthType:
    payment_success_percent: float
    open_report_rate_percent: float
    active_listing_percent: float
    active_seller_percent: float


@strawberry.type
class AdminAnalyticsType:
    user_growth: list[TimeSeriesPointType]
    seller_growth: list[TimeSeriesPointType]
    listing_growth: list[TimeSeriesPointType]
    revenue: list[TimeSeriesPointType]
    category_distribution: list[MetricType]
    plan_distribution: list[MetricType]
    verification_outcomes: list[MetricType]
    report_outcomes: list[MetricType]
    billing_activity: list[MetricType]
    health: MarketplaceHealthType
