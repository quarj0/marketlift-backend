from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from marketlift.common.models import UUIDTimeStampedModel


class SellerReview(UUIDTimeStampedModel):
    seller = models.ForeignKey(
        "sellers.SellerProfile", on_delete=models.CASCADE, related_name="reviews"
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="seller_reviews",
    )
    listing = models.ForeignKey(
        "listings.Listing",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviews",
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    comment = models.TextField(max_length=700)
    seller_reply = models.TextField(max_length=2000, blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)
    hidden_at = models.DateTimeField(null=True, blank=True)
    hidden_reason = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("seller", "hidden_at", "-created_at"),
                name="reviews_sel_hidden_idx",
            ),
            models.Index(
                fields=("reviewer", "-created_at"), name="reviews_rev_created_idx"
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("reviewer", "listing"),
                condition=models.Q(listing__isnull=False),
                name="reviews_one_per_reviewer_listing",
            )
        ]

    @property
    def visible(self):
        return self.hidden_at is None

    def __str__(self):
        return f"{self.reviewer} → {self.seller} ({self.rating}/5)"
