from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.contrib.gis.db import models as gis_models
from django.db import models, transaction
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
            seller_deleted_at__isnull=True,
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

    # Human-readable location snapshots remain on the listing for display, SEO,
    # and lexical marketplace search. `location_point` is private/internal and
    # powers PostGIS radius and distance calculations.
    country_code = models.CharField(max_length=2, blank=True, db_index=True)
    state = models.CharField(max_length=100, blank=True)
    state_code = models.CharField(max_length=8, blank=True)
    city = models.CharField(max_length=100)
    district = models.CharField(max_length=120, blank=True)
    location_point = gis_models.PointField(
        geography=True, srid=4326, null=True, blank=True, spatial_index=True
    )
    location_provider = models.CharField(max_length=40, blank=True)
    location_provider_id = models.CharField(max_length=120, blank=True)

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    views = models.PositiveBigIntegerField(default=0)
    published_at = models.DateTimeField(null=True, blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)
    sold_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    seller_deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    seller_delete_reason = models.TextField(blank=True)

    objects = ListingQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("status", "-created_at")),
            models.Index(fields=("category", "status", "-created_at")),
            models.Index(fields=("state_code", "city", "status")),
            models.Index(
                fields=("country_code", "state_code", "city", "status"),
                name="listings_country_loc_idx",
            ),
            models.Index(fields=("seller", "status")),
            models.Index(fields=("price",)),
            models.Index(
                fields=("status", "published_at"), name="listings_status_pub_idx"
            ),
            models.Index(
                fields=("state_code", "status", "-created_at"),
                name="listings_state_status_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.category_id:
            self.category_slug_snapshot = self.category.slug
            self.category_name_snapshot = self.category.name
            self.category_schema_version = self.category.schema_version

        if not self.slug:
            base = slugify(self.title)[:180] or "listing"
            self.slug = f"{base}-{str(self.id).split('-')[0]}"

        update_fields = kwargs.get("update_fields")
        super().save(*args, **kwargs)

        searchable_fields = {
            "title",
            "description",
            "category",
            "category_id",
            "country_code",
            "state",
            "state_code",
            "city",
            "district",
            "condition",
        }
        if update_fields is None or searchable_fields.intersection(update_fields):
            # Services create/update attributes in the same transaction. on_commit
            # therefore builds one coherent document after all listing data is saved.
            from marketlift.search.document import rebuild_listing_search_document

            listing_id = self.pk
            transaction.on_commit(lambda: rebuild_listing_search_document(listing_id))

    @property
    def category_slug(self) -> str:
        return self.category.slug if self.category_id else self.category_slug_snapshot

    @property
    def category_name(self) -> str:
        return self.category.name if self.category_id else self.category_name_snapshot

    @property
    def location_text(self) -> str:
        parts = [self.city, self.state_code, self.country_code]
        return ", ".join(part for part in parts if part)

    @property
    def is_publicly_visible(self) -> bool:
        return (
            self.status == self.Status.PUBLISHED
            and not self.seller.is_suspended
            and self.category_id is not None
            and self.category.active
            and self.seller_deleted_at is None
        )

    def __str__(self) -> str:
        return self.title


class ListingSearchDocument(models.Model):
    """PostgreSQL search projection kept separate from transactional listing rows."""

    listing = models.OneToOneField(
        Listing,
        on_delete=models.CASCADE,
        related_name="search_document",
        primary_key=True,
    )
    search_text = models.TextField(blank=True, editable=False)
    search_tokens = models.JSONField(default=list, blank=True, editable=False)
    search_vector = SearchVectorField(null=True, blank=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            GinIndex(fields=("search_vector",), name="listingdoc_vector_gin"),
            GinIndex(fields=("search_tokens",), name="listingdoc_tokens_gin"),
            GinIndex(
                fields=("search_text",),
                name="listingdoc_text_trgm",
                opclasses=("gin_trgm_ops",),
            ),
        ]

    def __str__(self) -> str:
        return f"Search document for {self.listing_id}"


class ListingMedia(UUIDTimeStampedModel):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="media")
    upload = models.OneToOneField(
        "uploads.UploadAsset",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="listing_media",
    )
    # Kept for legacy/external image URLs. New Marketlift uploads use `upload`.
    url = models.CharField(max_length=1000, blank=True)
    alt_text = models.CharField(max_length=180, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ("sort_order", "created_at")
        indexes = [models.Index(fields=("listing", "sort_order"))]

    @property
    def content_url(self) -> str:
        if self.upload_id:
            return self.upload.preferred_image_url("detail")
        return self.url

    def __str__(self) -> str:
        return self.content_url


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


class RecentlyViewedListing(UUIDTimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recently_viewed_listings",
    )
    listing = models.ForeignKey(
        Listing, on_delete=models.CASCADE, related_name="recent_viewers"
    )

    class Meta:
        ordering = ("-updated_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("user", "listing"), name="listings_unique_recent_view"
            )
        ]
        indexes = [
            models.Index(
                fields=("user", "-updated_at"), name="listings_recent_user_idx"
            )
        ]
