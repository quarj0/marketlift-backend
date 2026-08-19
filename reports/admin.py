from django.contrib import admin
from .models import Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "target_type",
        "target_label_snapshot",
        "reason",
        "priority",
        "status",
        "created_at",
    )
    list_filter = ("target_type", "reason", "priority", "status")
    search_fields = (
        "reference",
        "target_label_snapshot",
        "statement",
        "reporter__email",
    )
