from django.contrib import admin

from .models import ListingPromotion, PromotionProduct


@admin.register(PromotionProduct)
class PromotionProductAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "price", "duration_days", "active", "sort_order")
    list_filter = ("active",)
    search_fields = ("name", "code", "description")
    ordering = ("sort_order", "price")


@admin.register(ListingPromotion)
class ListingPromotionAdmin(admin.ModelAdmin):
    list_display = (
        "listing",
        "product",
        "source",
        "starts_at",
        "ends_at",
        "cancelled_at",
    )
    list_filter = ("source", "product")
    search_fields = ("listing__title", "listing__slug")
    raw_id_fields = ("listing",)
