from django.urls import include, path

from .sitemaps import SitemapView
from .telemetry import WebVitalsView
from .views import health, maintenance_status, market_profile, readiness

urlpatterns = [
    path("telemetry/web-vitals/", WebVitalsView.as_view(), name="web-vitals"),
    path("sitemap/", SitemapView.as_view(), name="sitemap-data"),
    path("health/", health, name="health"),
    path("maintenance/", maintenance_status, name="maintenance-status"),
    path("market/", market_profile, name="market-profile"),
    path("ready/", readiness, name="readiness"),
    path("auth/", include("marketlift.api.auth.urls")),
    path("search/", include("marketlift.api.search.urls")),
    path("locations/", include("marketlift.api.locations.urls")),
    path("uploads/", include("uploads.api.urls")),
    path("webhooks/", include("payments.api.urls")),
]
