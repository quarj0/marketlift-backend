from django.contrib import admin

from .models import (
    Market,
    PlatformConfiguration,
    PromotionProductMarketPrice,
    SellerPlanMarketPrice,
)


@admin.register(PlatformConfiguration)
class PlatformConfigurationAdmin(admin.ModelAdmin):
    list_display = ("marketplace_name", "maintenance_mode", "allow_new_registrations")


@admin.register(Market)
class MarketAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "country_name",
        "currency",
        "payment_provider",
        "is_enabled",
        "is_default",
        "sort_order",
    )
    list_filter = ("is_enabled", "is_default", "payment_provider")
    search_fields = ("code", "country_name", "currency")
    ordering = ("sort_order", "country_name")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    readonly_fields = (
        "code",
        "country_name",
        "locale",
        "django_language_code",
        "currency",
        "currency_symbol",
        "timezone",
        "geocoder_language",
        "identity_label",
        "identity_key",
        "currency_aliases",
        "currency_subunit_factor",
        "hierarchical_location_catalog",
    )


@admin.register(SellerPlanMarketPrice)
class SellerPlanMarketPriceAdmin(admin.ModelAdmin):
    list_display = ("market", "plan", "monthly_price", "yearly_price", "active")
    list_filter = ("market", "active")
    search_fields = ("market__code", "plan__code", "plan__name")


@admin.register(PromotionProductMarketPrice)
class PromotionProductMarketPriceAdmin(admin.ModelAdmin):
    list_display = ("market", "product", "price", "active")
    list_filter = ("market", "active")
    search_fields = ("market__code", "product__code", "product__name")
