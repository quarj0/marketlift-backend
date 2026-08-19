from django.urls import include, path
from .views import health, readiness

urlpatterns = [
    path("health/", health, name="health"),
    path("ready/", readiness, name="ready"),
    path("auth/", include("marketlift.api.auth.urls")),
]
