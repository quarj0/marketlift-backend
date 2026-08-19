from django.contrib import admin
from .models import SellerReview


@admin.register(SellerReview)
class SellerReviewAdmin(admin.ModelAdmin):
    list_display = ("id", "seller", "reviewer", "rating", "created_at", "hidden_at")
    list_filter = ("rating", "hidden_at")
    search_fields = (
        "seller__display_name",
        "seller__user__email",
        "reviewer__email",
        "comment",
    )
