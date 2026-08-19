from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from marketlift.common.models import UUIDTimeStampedModel


class ListingQuerySet(models.QuerySet):
    def public(self):
        return self.filter(
            status=Listing.Status.PUBLISHED,
            seller__is_suspended=False,
            category__isnull=False,
            category__active=True,
        )


class Listing(UUIDTimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        PAUSED = "paused", "Paused"
        SOLD = "sold", "Sold"
        EXPIRED = "expired", "Expired"
        UNDER_REVIEW = "under_review", "Under review"
        REJECTED = "rejected", "Rejected"
        REMOVED = "removed", "Removed"

    class Condition(models.TextChoices):
        NEW = "New", "New"
        LIKE_NEW = "Like new", "Like new"
        USED = "Used", "Used"

    seller = models.ForeignKey(
        "sellers.SellerProfile",
        on_delete=models.PROTECT,
        related_name="listings",
    )
    category = models.ForeignKey(
        "categories.Category",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="listings",
    )
    category_slug_snapshot = models.SlugField(max_length=80, blank=True)
    category_name_snapshot = models.CharField(max_length=120, blank=True)
    category_schema_version = models.PositiveIntegerField(default=1)

    slug = models.SlugField(max_length=220, unique=True, blank=True)
    title = models.CharField(max_length=180)
    description = models.TextField()
    price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    condition = models.CharField(max_length=16, choices=Condition.choices, blank=True)
    negotiable = models.BooleanField(default=False)

    state = models.CharField(max_length=100)
    state_code = models.CharField(max_length=8)
    city = models.CharField(max_length=100)
    district = models.CharField(max_length=120, blank=True)

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    views = models.PositiveBigIntegerField(default=0)
    published_at = models.DateTimeField(null=True, blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)
    sold_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)

    objects = ListingQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("status", "-created_at")),
            models.Index(fields=("category", "status", "-created_at")),
            models.Index(fields=("state_code", "city", "status")),
            models.Index(fields=("seller", "status")),
            models.Index(fields=("price",)),
        ]

    def save(self, *args, **kwargs):
        if self.category_id:
            self.category_slug_snapshot = self.category.slug
            self.category_name_snapshot = self.category.name
            self.category_schema_version = self.category.schema_version

        if not self.slug:
            base = slugify(self.title)[:180] or "listing"
            self.slug = f"{base}-{str(self.id).split('-')[0]}"

        super().save(*args, **kwargs)

    @property
    def category_slug(self) -> str:
        return self.category.slug if self.category_id else self.category_slug_snapshot

    @property
    def category_name(self) -> str:
        return self.category.name if self.category_id else self.category_name_snapshot

    @property
    def location_text(self) -> str:
        return f"{self.city}, {self.state_code}"

    @property
    def is_publicly_visible(self) -> bool:
        return (
            self.status == self.Status.PUBLISHED
            and not self.seller.is_suspended
            and self.category_id is not None
            and self.category.active
        )

    def __str__(self) -> str:
        return self.title


class ListingMedia(UUIDTimeStampedModel):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="media")
    url = models.URLField(max_length=1000)
    alt_text = models.CharField(max_length=180, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ("sort_order", "created_at")
        indexes = [models.Index(fields=("listing", "sort_order"))]

    def __str__(self) -> str:
        return self.url


class ListingAttribute(UUIDTimeStampedModel):
    listing = models.ForeignKey(
        Listing, on_delete=models.CASCADE, related_name="attribute_values"
    )
    field = models.ForeignKey(
        "categories.CategoryField",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="listing_values",
    )
    key = models.SlugField(max_length=80)
    label_snapshot = models.CharField(max_length=120)
    field_type_snapshot = models.CharField(max_length=16)
    text_value = models.TextField(null=True, blank=True)
    number_value = models.DecimalField(
        max_digits=18, decimal_places=4, null=True, blank=True
    )
    boolean_value = models.BooleanField(null=True, blank=True)

    class Meta:
        ordering = ("key",)
        constraints = [
            models.UniqueConstraint(
                fields=("listing", "key"),
                name="listings_unique_attribute_key",
            )
        ]
        indexes = [
            models.Index(fields=("key", "text_value")),
            models.Index(fields=("key", "number_value")),
            models.Index(fields=("key", "boolean_value")),
        ]

    @property
    def value(self):
        if self.field_type_snapshot == "boolean":
            return self.boolean_value
        if self.field_type_snapshot == "number":
            return self.number_value
        return self.text_value

    def __str__(self) -> str:
        return f"{self.listing_id}.{self.key}"


class SavedListing(UUIDTimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_listings",
    )
    listing = models.ForeignKey(
        Listing,
        on_delete=models.CASCADE,
        related_name="saved_by",
    )

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("user", "listing"),
                name="listings_unique_saved_listing",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user_id} saved {self.listing_id}"
