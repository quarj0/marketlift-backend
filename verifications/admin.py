from django.contrib import admin
from .models import VerificationSubmission


@admin.register(VerificationSubmission)
class VerificationSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "seller",
        "status",
        "risk_level",
        "cpf_masked",
        "submitted_at",
        "decided_at",
    )
    list_filter = ("status", "risk_level", "document_type")
    search_fields = (
        "seller__display_name",
        "seller__user__full_name",
        "seller__user__email",
        "cpf_masked",
        "provider_reference",
    )
    readonly_fields = (
        "cpf_digest",
        "cpf_masked",
        "submitted_at",
        "decided_at",
        "created_at",
        "updated_at",
    )
