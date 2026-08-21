from django.urls import path

from .views import ListingSearchView

urlpatterns = [
    path("listings/", ListingSearchView.as_view(), name="listing-search"),
]
