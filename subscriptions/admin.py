from django.contrib import admin

from .models import SellerPlan, SellerSubscription


@admin.register(SellerPlan)
class SellerPlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "monthly_price",
        "yearly_price",
        "listing_limit",
        "promotion_credits",
        "active",
        "recommended",
    )
    list_filter = ("active", "recommended")
    search_fields = ("name", "code")
    ordering = ("sort_order", "monthly_price")


@admin.register(SellerSubscription)
class SellerSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("seller", "plan", "billing_cycle", "status", "current_period_end")
    list_filter = ("status", "billing_cycle", "plan")
    search_fields = ("seller__user__email", "seller__display_name", "plan__name")
    raw_id_fields = ("seller",)
