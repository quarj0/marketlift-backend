from django.contrib import admin
from .models import ModerationCase


@admin.register(ModerationCase)
class ModerationCaseAdmin(admin.ModelAdmin):
    list_display = (
        "listing",
        "status",
        "source",
        "opened_by",
        "decided_by",
        "created_at",
        "decided_at",
    )
    list_filter = ("status", "source")
    search_fields = ("listing__title", "review_reason", "decision_reason")
