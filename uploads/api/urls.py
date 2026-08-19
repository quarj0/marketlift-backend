from django.urls import path

from .views import (
    CompleteUploadView,
    PrepareUploadView,
    UploadContentView,
    UploadDeleteView,
)

app_name = "uploads"

urlpatterns = [
    path("prepare/", PrepareUploadView.as_view(), name="prepare"),
    path("<uuid:asset_id>/content/", UploadContentView.as_view(), name="content"),
    path("<uuid:asset_id>/complete/", CompleteUploadView.as_view(), name="complete"),
    path("<uuid:asset_id>/", UploadDeleteView.as_view(), name="delete"),
]
