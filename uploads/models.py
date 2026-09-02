from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from marketlift.common.models import UUIDTimeStampedModel


class UploadAsset(UUIDTimeStampedModel):
    class Purpose(models.TextChoices):
        LISTING_IMAGE = "listing_image", "Listing image"
        MESSAGE_IMAGE = "message_image", "Message image"
        VERIFICATION_DOCUMENT = "verification_document", "Verification document"
        VERIFICATION_SELFIE = "verification_selfie", "Verification selfie"
        REPORT_EVIDENCE = "report_evidence", "Report evidence"
        AVATAR = "avatar", "Avatar"
        CATEGORY_IMAGE = "category_image", "Category image"
        SUPPORT_ATTACHMENT = "support_attachment", "Support attachment"

    class Status(models.TextChoices):
        PREPARED = "prepared", "Prepared"
        READY = "ready", "Ready"
        ATTACHED = "attached", "Attached"
        DELETED = "deleted", "Deleted"
        EXPIRED = "expired", "Expired"

    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public"
        PRIVATE = "private", "Private"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="uploads",
    )
    purpose = models.CharField(max_length=32, choices=Purpose.choices, db_index=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PREPARED,
        db_index=True,
    )
    visibility = models.CharField(
        max_length=16,
        choices=Visibility.choices,
        default=Visibility.PRIVATE,
    )

    # `storage_alias` and `object_key` deliberately describe logical storage,
    # not a vendor. Provider credentials and SDK behavior live behind the
    # storage backend interface.
    storage_alias = models.CharField(max_length=64, default="default")
    object_key = models.CharField(max_length=500, unique=True)
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=120)
    expected_size = models.PositiveBigIntegerField()
    actual_size = models.PositiveBigIntegerField(null=True, blank=True)
    checksum_sha256 = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    expires_at = models.DateTimeField(db_index=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    attached_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("owner", "status", "-created_at")),
            models.Index(fields=("purpose", "status", "expires_at")),
        ]

    @property
    def expired(self) -> bool:
        return self.expires_at <= timezone.now()

    @property
    def content_url(self) -> str:
        return f"/api/v1/uploads/{self.id}/content/"

    def variant_url(self, kind: str) -> str | None:
        cache = getattr(self, "_prefetched_objects_cache", {})
        if "variants" in cache:
            variant = next(
                (item for item in cache["variants"] if item.kind == kind), None
            )
        else:
            variant = self.variants.filter(kind=kind).first()
        return variant.content_url if variant else None

    def preferred_image_url(self, kind: str = "detail") -> str:
        return self.variant_url(kind) or self.content_url

    def __str__(self) -> str:
        return f"{self.purpose}: {self.original_name}"


class UploadVariant(UUIDTimeStampedModel):
    asset = models.ForeignKey(
        UploadAsset, on_delete=models.CASCADE, related_name="variants"
    )
    kind = models.CharField(max_length=32)
    storage_alias = models.CharField(max_length=64, default="default")
    object_key = models.CharField(max_length=500, unique=True)
    mime_type = models.CharField(max_length=120, default="image/webp")
    size = models.PositiveBigIntegerField(default=0)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("asset", "kind"), name="uploads_unique_asset_variant"
            )
        ]
        indexes = [
            models.Index(fields=("asset", "kind"), name="uploads_asset_kind_idx")
        ]

    @property
    def content_url(self):
        return f"/api/v1/uploads/{self.asset_id}/variants/{self.kind}/"
