from django.contrib import admin

from .models import SellerProfile


@admin.register(SellerProfile)
class SellerProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "seller_type",
        "verified_at",
        "is_suspended",
        "activated_at",
    )
    list_filter = ("seller_type", "is_suspended")
    search_fields = ("user__email", "user__full_name", "display_name")
    readonly_fields = ("activated_at", "created_at", "updated_at")
