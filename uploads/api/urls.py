from django.urls import path
from .views import (
    CompleteUploadView,
    PrepareUploadView,
    UploadContentView,
    UploadDeleteView,
    UploadVariantView,
)

urlpatterns = [
    path("prepare/", PrepareUploadView.as_view(), name="upload-prepare"),
    path(
        "<uuid:asset_id>/content/", UploadContentView.as_view(), name="upload-content"
    ),
    path(
        "<uuid:asset_id>/complete/",
        CompleteUploadView.as_view(),
        name="upload-complete",
    ),
    path("<uuid:asset_id>/", UploadDeleteView.as_view(), name="upload-delete"),
    path(
        "<uuid:asset_id>/variants/<str:kind>/",
        UploadVariantView.as_view(),
        name="upload-variant",
    ),
]
