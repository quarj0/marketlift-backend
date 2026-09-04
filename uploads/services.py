from __future__ import annotations

import mimetypes
import uuid
from copy import copy
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import UploadAsset
from .storage import get_storage_backend

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
DOCUMENT_TYPES = IMAGE_TYPES | {"application/pdf"}

PURPOSE_RULES = {
    UploadAsset.Purpose.LISTING_IMAGE: (
        IMAGE_TYPES,
        10 * 1024 * 1024,
        UploadAsset.Visibility.PUBLIC,
    ),
    UploadAsset.Purpose.MESSAGE_IMAGE: (
        IMAGE_TYPES,
        10 * 1024 * 1024,
        UploadAsset.Visibility.PRIVATE,
    ),
    UploadAsset.Purpose.VERIFICATION_DOCUMENT: (
        DOCUMENT_TYPES,
        15 * 1024 * 1024,
        UploadAsset.Visibility.PRIVATE,
    ),
    UploadAsset.Purpose.VERIFICATION_SELFIE: (
        IMAGE_TYPES,
        10 * 1024 * 1024,
        UploadAsset.Visibility.PRIVATE,
    ),
    UploadAsset.Purpose.REPORT_EVIDENCE: (
        DOCUMENT_TYPES,
        15 * 1024 * 1024,
        UploadAsset.Visibility.PRIVATE,
    ),
    UploadAsset.Purpose.AVATAR: (
        IMAGE_TYPES,
        5 * 1024 * 1024,
        UploadAsset.Visibility.PUBLIC,
    ),
    UploadAsset.Purpose.CATEGORY_IMAGE: (
        IMAGE_TYPES,
        5 * 1024 * 1024,
        UploadAsset.Visibility.PUBLIC,
    ),
    UploadAsset.Purpose.SUPPORT_ATTACHMENT: (
        DOCUMENT_TYPES,
        15 * 1024 * 1024,
        UploadAsset.Visibility.PRIVATE,
    ),
}


def _staging_storage_alias() -> str:
    return str(
        getattr(settings, "MARKETLIFT_UPLOAD_STAGING_ALIAS", "default") or "default"
    )


def _final_storage_alias(purpose: str) -> str:
    aliases = getattr(settings, "MARKETLIFT_UPLOAD_PURPOSE_ALIASES", {})
    return str(aliases.get(purpose) or "default")


def _promote_upload_storage(asset: UploadAsset) -> UploadAsset:
    """Copy a validated staging object into its purpose-specific logical store."""
    destination_alias = _final_storage_alias(asset.purpose)
    if destination_alias == asset.storage_alias:
        return asset

    source_backend = get_storage_backend(asset.storage_alias)
    destination_backend = get_storage_backend(destination_alias)
    destination_asset = copy(asset)
    destination_asset.storage_alias = destination_alias

    try:
        with source_backend.open(asset) as stream:
            info = destination_backend.store(
                destination_asset,
                stream,
                content_length=asset.actual_size or asset.expected_size,
            )
    except FileNotFoundError as exc:
        raise ValidationError("The uploaded object could not be found.") from exc

    if info.size != asset.expected_size:
        destination_backend.delete(destination_asset)
        raise ValidationError(
            {"size": "Stored file size changed while finalizing upload."}
        )

    previous_alias = asset.storage_alias
    asset.storage_alias = destination_alias
    asset.actual_size = info.size
    asset.checksum_sha256 = info.checksum_sha256 or asset.checksum_sha256
    asset.save(
        update_fields=("storage_alias", "actual_size", "checksum_sha256", "updated_at")
    )
    try:
        source_copy = copy(asset)
        source_copy.storage_alias = previous_alias
        source_backend.delete(source_copy)
    except Exception:
        # The destination is already durable. Abandoned staging objects are also
        # removed by Marketlift cleanup and should have a provider lifecycle rule.
        pass
    return asset


def _delete_stored_objects(asset: UploadAsset) -> None:
    """Delete an upload and all generated variants from their logical stores."""
    variants = list(asset.variants.all())
    for variant in variants:
        try:
            get_storage_backend(variant.storage_alias).delete(variant)
        except FileNotFoundError:
            pass
        variant.delete()
    try:
        get_storage_backend(asset.storage_alias).delete(asset)
    except FileNotFoundError:
        pass


MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
}


def _rule(purpose: str):
    try:
        return PURPOSE_RULES[purpose]
    except KeyError as exc:
        raise ValidationError({"purpose": "Unsupported upload purpose."}) from exc


def _safe_name(value: str) -> str:
    name = Path(value or "upload").name.strip()
    return name[:255] or "upload"


def prepare_upload(
    *, user, purpose: str, original_name: str, mime_type: str, size: int, request=None
):
    allowed_types, max_size, visibility = _rule(purpose)
    mime_type = (mime_type or "").lower().strip()
    if mime_type not in allowed_types:
        raise ValidationError(
            {
                "mimeType": "This file type is not allowed for the selected upload purpose."
            }
        )
    try:
        size = int(size)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"size": "A valid file size is required."}) from exc
    if size <= 0:
        raise ValidationError({"size": "The file must not be empty."})
    if size > max_size:
        raise ValidationError(
            {"size": f"The maximum file size is {max_size // (1024 * 1024)} MB."}
        )

    extension = (
        MIME_EXTENSIONS.get(mime_type) or mimetypes.guess_extension(mime_type) or ""
    )
    object_key = (
        f"{purpose}/{user.pk}/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{extension}"
    )
    asset = UploadAsset.objects.create(
        owner=user,
        purpose=purpose,
        visibility=visibility,
        storage_alias=_staging_storage_alias(),
        object_key=object_key,
        original_name=_safe_name(original_name),
        mime_type=mime_type,
        expected_size=size,
        expires_at=timezone.now() + timedelta(hours=24),
    )
    target = get_storage_backend(asset.storage_alias).prepare_upload(
        asset, request=request
    )
    return asset, target


def _owned_pending_asset(*, asset, user):
    if asset.owner_id != user.pk:
        raise PermissionDenied("This upload belongs to another account.")
    if asset.status not in {UploadAsset.Status.PREPARED, UploadAsset.Status.READY}:
        raise ValidationError("This upload can no longer be changed.")
    if asset.expired:
        raise ValidationError("This upload has expired. Prepare a new upload.")
    return asset


def store_proxy_upload(
    *, asset, user, stream, content_type: str = "", content_length: int | None = None
):
    _owned_pending_asset(asset=asset, user=user)
    if asset.status != UploadAsset.Status.PREPARED:
        raise ValidationError("This upload has already been completed.")
    if (
        content_type
        and content_type.split(";", 1)[0].strip().lower() != asset.mime_type
    ):
        raise ValidationError(
            {"mimeType": "Uploaded content type does not match the prepared upload."}
        )
    backend = get_storage_backend(asset.storage_alias)
    if not backend.supports_proxy_upload:
        raise ValidationError(
            "The configured storage backend expects direct provider uploads."
        )
    if content_length is not None and int(content_length) > asset.expected_size:
        raise ValidationError(
            {"size": "Uploaded content is larger than the prepared upload."}
        )
    info = backend.store(asset, stream, content_length=content_length)
    if info.size != asset.expected_size:
        backend.delete(asset)
        raise ValidationError(
            {"size": "Uploaded file size does not match the prepared upload."}
        )
    asset.actual_size = info.size
    asset.checksum_sha256 = info.checksum_sha256
    asset.save(update_fields=("actual_size", "checksum_sha256", "updated_at"))
    return asset


def complete_upload(*, asset, user):
    _owned_pending_asset(asset=asset, user=user)
    try:
        info = get_storage_backend(asset.storage_alias).stat(asset)
    except FileNotFoundError as exc:
        raise ValidationError("The uploaded object could not be found.") from exc
    if info.size != asset.expected_size:
        raise ValidationError(
            {"size": "Stored file size does not match the prepared upload."}
        )
    if getattr(settings, "MARKETLIFT_STRICT_UPLOAD_VALIDATION", True):
        try:
            if asset.mime_type.startswith("image/"):
                from .processing import validate_image_asset

                validate_image_asset(asset)
            elif asset.mime_type == "application/pdf":
                from .processing import validate_pdf_asset

                validate_pdf_asset(asset)
        except ValueError as exc:
            _delete_stored_objects(asset)
            raise ValidationError(str(exc)) from exc

    asset.actual_size = info.size
    asset.checksum_sha256 = info.checksum_sha256 or asset.checksum_sha256
    asset.save(update_fields=("actual_size", "checksum_sha256", "updated_at"))
    asset = _promote_upload_storage(asset)
    info = get_storage_backend(asset.storage_alias).stat(asset)
    asset.actual_size = info.size
    asset.checksum_sha256 = info.checksum_sha256 or asset.checksum_sha256
    asset.status = UploadAsset.Status.READY
    asset.ready_at = timezone.now()
    asset.save(
        update_fields=(
            "actual_size",
            "checksum_sha256",
            "status",
            "ready_at",
            "updated_at",
        )
    )
    if asset.mime_type.startswith("image/"):
        if getattr(settings, "MARKETLIFT_PROCESS_UPLOADS_ASYNC", False):
            from .tasks import process_upload_image

            transaction.on_commit(lambda: process_upload_image.delay(str(asset.id)))
        else:
            from .processing import process_image_asset

            process_image_asset(asset)
    return asset


@transaction.atomic
def claim_upload(*, asset, user, purpose: str):
    asset = UploadAsset.objects.select_for_update().get(pk=asset.pk)
    if asset.owner_id != user.pk:
        raise PermissionDenied("This upload belongs to another account.")
    if asset.purpose != purpose:
        raise ValidationError("This upload was prepared for a different purpose.")
    if asset.status != UploadAsset.Status.READY:
        raise ValidationError("Complete the upload before attaching it.")
    if asset.expired:
        raise ValidationError("This upload has expired.")
    asset.status = UploadAsset.Status.ATTACHED
    asset.attached_at = timezone.now()
    asset.save(update_fields=("status", "attached_at", "updated_at"))
    return asset


def delete_unattached_upload(*, asset, user):
    if asset.owner_id != user.pk:
        raise PermissionDenied("This upload belongs to another account.")
    if asset.status == UploadAsset.Status.ATTACHED:
        raise ValidationError(
            "Attached uploads are removed through their owning domain object."
        )
    _delete_stored_objects(asset)
    asset.status = UploadAsset.Status.DELETED
    asset.deleted_at = timezone.now()
    asset.save(update_fields=("status", "deleted_at", "updated_at"))
    return asset


def delete_unattached_uploads(*, upload_ids, user, purpose: str | None = None) -> int:
    """Best-effort cleanup for a failed domain mutation's staged uploads."""
    queryset = UploadAsset.objects.filter(
        id__in=list(upload_ids or []),
        owner=user,
        status__in=(UploadAsset.Status.PREPARED, UploadAsset.Status.READY),
    )
    if purpose:
        queryset = queryset.filter(purpose=purpose)

    deleted = 0
    for asset in queryset.prefetch_related("variants"):
        try:
            delete_unattached_upload(asset=asset, user=user)
        except Exception:
            # The scheduled abandoned-upload cleanup remains the final safety net.
            continue
        deleted += 1
    return deleted


def retire_upload(*, asset):
    """Remove an attachment's stored object when its domain owner replaces it."""
    if asset.status == UploadAsset.Status.DELETED:
        return asset
    _delete_stored_objects(asset)
    asset.status = UploadAsset.Status.DELETED
    asset.deleted_at = timezone.now()
    asset.save(update_fields=("status", "deleted_at", "updated_at"))
    return asset


def can_access_upload(*, asset, user=None) -> bool:
    if (
        asset.purpose
        in {UploadAsset.Purpose.AVATAR, UploadAsset.Purpose.CATEGORY_IMAGE}
        and asset.visibility == UploadAsset.Visibility.PUBLIC
        and asset.status == UploadAsset.Status.ATTACHED
    ):
        return True

    if user is not None and getattr(user, "is_authenticated", False):
        if user.is_staff or asset.owner_id == user.pk:
            return True

    listing_media = getattr(asset, "listing_media", None)
    if listing_media is not None:
        try:
            media = listing_media
            listing = media.listing
            if listing.is_publicly_visible:
                return True
            if user is not None and getattr(user, "is_authenticated", False):
                return listing.seller.user_id == user.pk
        except Exception:
            pass

    message_attachment = getattr(asset, "message_attachment", None)
    if (
        message_attachment is not None
        and user is not None
        and getattr(user, "is_authenticated", False)
    ):
        try:
            return message_attachment.message.conversation.includes_user(user)
        except Exception:
            pass

    return False


def expire_abandoned_uploads(*, now=None) -> int:
    now = now or timezone.now()
    assets = list(
        UploadAsset.objects.filter(
            status__in=[UploadAsset.Status.PREPARED, UploadAsset.Status.READY],
            expires_at__lte=now,
        )[:500]
    )
    for asset in assets:
        _delete_stored_objects(asset)
        asset.status = UploadAsset.Status.EXPIRED
        asset.deleted_at = now
        asset.save(update_fields=("status", "deleted_at", "updated_at"))
    return len(assets)
