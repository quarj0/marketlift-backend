from django.contrib import admin

from .models import Category, CategoryField, CategoryFieldOption


class CategoryFieldOptionInline(admin.TabularInline):
    model = CategoryFieldOption
    extra = 0


@admin.register(CategoryField)
class CategoryFieldAdmin(admin.ModelAdmin):
    list_display = ("category", "key", "label", "field_type", "required", "filterable")
    list_filter = ("field_type", "required", "filterable", "category")
    search_fields = ("category__name", "category__slug", "key", "label")
    ordering = ("category__sort_order", "category__name", "sort_order")
    inlines = (CategoryFieldOptionInline,)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "active", "schema_version", "sort_order", "updated_at")
    list_filter = ("active", "pricing_mode", "condition_enabled")
    search_fields = ("name", "slug", "description")
    ordering = ("sort_order", "name")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(CategoryFieldOption)
class CategoryFieldOptionAdmin(admin.ModelAdmin):
    list_display = ("field", "value", "label", "sort_order")
    search_fields = ("field__label", "field__key", "value", "label")
