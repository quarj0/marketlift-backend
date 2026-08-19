from django.conf import settings
from django.db import models
from marketlift.common.models import UUIDTimeStampedModel


class SavedSearch(UUIDTimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_searches",
    )
    name = models.CharField(max_length=120, blank=True)
    criteria = models.JSONField(default=dict)
    alerts_enabled = models.BooleanField(default=True)
    active = models.BooleanField(default=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("user", "active", "-created_at"),
                name="savedsearch_user_active_idx",
            ),
            models.Index(
                fields=("alerts_enabled", "active", "last_checked_at"),
                name="savedsearch_alert_idx",
            ),
        ]


class SavedSearchMatch(UUIDTimeStampedModel):
    saved_search = models.ForeignKey(
        SavedSearch, on_delete=models.CASCADE, related_name="matches"
    )
    listing = models.ForeignKey(
        "listings.Listing",
        on_delete=models.CASCADE,
        related_name="saved_search_matches",
    )
    notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("saved_search", "listing"), name="saved_searches_unique_match"
            )
        ]
        indexes = [
            models.Index(
                fields=("saved_search", "notified_at"),
                name="savedsearch_match_notif_idx",
            )
        ]
