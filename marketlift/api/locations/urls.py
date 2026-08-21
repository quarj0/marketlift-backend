from django.urls import path

from .views import LocationReverseView, LocationSearchView

urlpatterns = [
    path("search/", LocationSearchView.as_view(), name="location-search"),
    path("reverse/", LocationReverseView.as_view(), name="location-reverse"),
]
