from django.contrib import admin
from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "seller",
        "purpose",
        "amount",
        "method",
        "status",
        "provider",
        "created_at",
    )
    list_filter = ("purpose", "method", "status", "provider")
    search_fields = (
        "reference",
        "provider_order_id",
        "provider_payment_id",
        "seller__display_name",
        "seller__user__email",
    )
    readonly_fields = (
        "reference",
        "idempotency_key",
        "provider_order_id",
        "provider_payment_id",
        "checkout_data",
        "paid_at",
        "failed_at",
        "cancelled_at",
        "refunded_at",
        "created_at",
        "updated_at",
    )
