from django.contrib import admin
from .models import SellerProfile


@admin.register(SellerProfile)
class SellerProfileAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "seller_type",
        "verified_at",
        "is_suspended",
        "activated_at",
    )
    list_filter = ("seller_type", "is_suspended")
    search_fields = ("display_name", "user__email", "user__full_name")
