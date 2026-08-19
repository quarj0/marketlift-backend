from django.contrib import admin

from .models import UploadAsset


@admin.register(UploadAsset)
class UploadAssetAdmin(admin.ModelAdmin):
    list_display = (
        "original_name",
        "purpose",
        "owner",
        "status",
        "expected_size",
        "created_at",
    )
    list_filter = ("purpose", "status", "visibility")
    search_fields = ("original_name", "object_key", "owner__email")
    readonly_fields = (
        "object_key",
        "checksum_sha256",
        "ready_at",
        "attached_at",
        "deleted_at",
        "created_at",
        "updated_at",
    )
