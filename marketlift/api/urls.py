from django.urls import include, path

from .views import health, market_profile, readiness

urlpatterns = [
    path("health/", health, name="health"),
    path("market/", market_profile, name="market-profile"),
    path("ready/", readiness, name="readiness"),
    path("auth/", include("marketlift.api.auth.urls")),
    path("search/", include("marketlift.api.search.urls")),
    path("locations/", include("marketlift.api.locations.urls")),
    path("uploads/", include("uploads.api.urls")),
    path("webhooks/", include("payments.api.urls")),
]
