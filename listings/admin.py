from django.contrib import admin

from .models import Listing, ListingAttribute, ListingMedia, SavedListing


class ListingMediaInline(admin.TabularInline):
    model = ListingMedia
    extra = 0


class ListingAttributeInline(admin.TabularInline):
    model = ListingAttribute
    extra = 0
    readonly_fields = ("field", "key", "label_snapshot", "field_type_snapshot")


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ("title", "seller", "category_name", "price", "status", "city", "created_at")
    list_filter = ("status", "condition", "category", "state_code")
    search_fields = ("title", "slug", "description", "seller__display_name", "seller__user__email")
    readonly_fields = (
        "slug",
        "category_slug_snapshot",
        "category_name_snapshot",
        "category_schema_version",
        "views",
        "created_at",
        "updated_at",
    )
    raw_id_fields = ("seller",)
    inlines = (ListingMediaInline, ListingAttributeInline)


@admin.register(SavedListing)
class SavedListingAdmin(admin.ModelAdmin):
    list_display = ("user", "listing", "created_at")
    search_fields = ("user__email", "listing__title", "listing__slug")
    raw_id_fields = ("user", "listing")


@admin.register(ListingMedia)
class ListingMediaAdmin(admin.ModelAdmin):
    list_display = ("listing", "sort_order", "is_primary", "url")
    search_fields = ("listing__title", "listing__slug", "url")


@admin.register(ListingAttribute)
class ListingAttributeAdmin(admin.ModelAdmin):
    list_display = ("listing", "key", "label_snapshot", "field_type_snapshot")
    search_fields = ("listing__title", "key", "label_snapshot")
