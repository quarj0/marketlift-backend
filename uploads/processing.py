from io import BytesIO
from pathlib import PurePosixPath
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError
from .models import UploadAsset, UploadVariant
from .storage import get_storage_backend

IMAGE_MIME_BY_FORMAT = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}
VARIANTS = {
    "thumbnail": (320, 320, 78),
    "card": (720, 720, 80),
    "detail": (1600, 1600, 84),
}


def validate_image_asset(asset):
    backend = get_storage_backend(asset.storage_alias)
    try:
        with backend.open(asset) as fp:
            image = Image.open(fp)
            fmt = image.format
            image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Uploaded image content is invalid.") from exc
    actual = IMAGE_MIME_BY_FORMAT.get(fmt)
    if actual and asset.mime_type != actual:
        raise ValueError(
            "Uploaded image content does not match its declared MIME type."
        )
    return True


def process_image_asset(asset):
    if not asset.mime_type.startswith("image/"):
        return 0
    backend = get_storage_backend(asset.storage_alias)
    created = 0
    try:
        with backend.open(asset) as fp:
            image = ImageOps.exif_transpose(Image.open(fp))
            image.seek(0)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            for kind, (mw, mh, quality) in VARIANTS.items():
                im = image.copy()
                im.thumbnail((mw, mh), Image.Resampling.LANCZOS)
                if im.mode == "RGBA":
                    canvas = Image.new("RGB", im.size, "white")
                    canvas.paste(im, mask=im.getchannel("A"))
                    im = canvas
                elif im.mode != "RGB":
                    im = im.convert("RGB")
                buf = BytesIO()
                im.save(buf, format="WEBP", quality=quality, method=4)
                buf.seek(0)
                base = str(PurePosixPath(asset.object_key).with_suffix(""))
                key = f"{base}.{kind}.webp"
                variant, _ = UploadVariant.objects.update_or_create(
                    asset=asset,
                    kind=kind,
                    defaults={
                        "storage_alias": asset.storage_alias,
                        "object_key": key,
                        "mime_type": "image/webp",
                        "width": im.width,
                        "height": im.height,
                    },
                )
                info = backend.store(
                    variant, buf, content_length=buf.getbuffer().nbytes
                )
                variant.size = info.size
                variant.save(update_fields=("size", "updated_at"))
                created += 1
        asset.processed_at = timezone.now()
        asset.processing_error = ""
        asset.save(update_fields=("processed_at", "processing_error", "updated_at"))
        return created
    except Exception as exc:
        asset.processing_error = str(exc)[:1000]
        asset.save(update_fields=("processing_error", "updated_at"))
        raise


def validate_pdf_asset(asset):
    backend = get_storage_backend(asset.storage_alias)
    try:
        with backend.open(asset) as fp:
            header = fp.read(8)
    except OSError as exc:
        raise ValueError("Uploaded document content is invalid.") from exc
    if not header.startswith(b"%PDF-"):
        raise ValueError(
            "Uploaded document content does not match its declared PDF MIME type."
        )
    return True
