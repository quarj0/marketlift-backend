from django.urls import path

from .views import NeighborhoodSuggestionsView

urlpatterns = [
    path(
        "neighborhoods/",
        NeighborhoodSuggestionsView.as_view(),
        name="location-neighborhoods",
    ),
]
