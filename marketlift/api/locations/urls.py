from django.urls import path

from .views import (
    LocationCitiesView,
    LocationRegionsView,
    LocationReverseView,
    LocationSearchView,
    LocationStatesView,
    NeighborhoodSuggestionsView,
)

urlpatterns = [
    path("regions/", LocationRegionsView.as_view(), name="location-regions"),
    path("states/", LocationStatesView.as_view(), name="location-states"),
    path("cities/", LocationCitiesView.as_view(), name="location-cities"),
    path(
        "neighborhoods/",
        NeighborhoodSuggestionsView.as_view(),
        name="location-neighborhoods",
    ),
    path("search/", LocationSearchView.as_view(), name="location-search"),
    path("reverse/", LocationReverseView.as_view(), name="location-reverse"),
]
