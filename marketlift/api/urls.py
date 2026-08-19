from django.urls import include, path

from .views import health, readiness

urlpatterns = [
    path("health/", health, name="health"),
    path("ready/", readiness, name="readiness"),
    path("auth/", include("marketlift.api.auth.urls")),
    path("uploads/", include("uploads.api.urls")),
    path("webhooks/", include("payments.api.urls")),
]
