from io import BytesIO
import re
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
SCREENSHOT_NAME_RE = re.compile(
    r"(screen[\s_-]*shot|screenshot|screencap|print[\s_-]*screen|captura[\s_-]*(de[\s_-]*)?(tela|pantalla))",
    re.IGNORECASE,
)

COMMON_SCREEN_SIZES = {
    (1280, 720), (1366, 768), (1440, 900), (1536, 864), (1600, 900),
    (1920, 1080), (2560, 1440), (3840, 2160),
    (720, 1280), (768, 1366), (900, 1440), (864, 1536), (900, 1600),
    (1080, 1920), (1080, 2340), (1080, 2400), (1080, 2460),
    (1170, 2532), (1179, 2556), (1242, 2688), (1284, 2778),
    (1290, 2796), (1440, 2960), (1440, 3040), (1440, 3088),
    (1440, 3200),
}


def _dhash(image) -> str:
    grayscale = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(grayscale.getdata())
    bits = 0
    for y in range(8):
        row = y * 9
        for x in range(8):
            bits = (bits << 1) | int(
                pixels[row + x] > pixels[row + x + 1]
            )
    return f"{bits:016x}"


def _looks_like_screenshot(asset, image, fmt: str | None, exif) -> bool:
    if SCREENSHOT_NAME_RE.search(asset.original_name or ""):
        return True
    software = str(exif.get(305, "") if exif else "").casefold()
    if "screenshot" in software or "screen shot" in software:
        return True
    return (
        fmt == "PNG"
        and not exif
        and tuple(image.size) in COMMON_SCREEN_SIZES
    )


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
            image.load()
            image = ImageOps.exif_transpose(image)
            exif = image.getexif()
            width, height = image.size
            perceptual_hash = _dhash(image)
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Uploaded image content is invalid.") from exc

    actual = IMAGE_MIME_BY_FORMAT.get(fmt)
    if actual and asset.mime_type != actual:
        raise ValueError(
            "Uploaded image content does not match its declared MIME type."
        )

    if asset.purpose == UploadAsset.Purpose.LISTING_IMAGE:
        if width < 400:
            raise ValueError(
                "Listing photos must be at least 400 pixels wide."
            )
        if _looks_like_screenshot(asset, image, fmt, exif):
            raise ValueError(
                "Screenshots are not allowed. Upload a real photo of the item."
            )

    asset.metadata = {
        **(asset.metadata or {}),
        "image_width": width,
        "image_height": height,
        "perceptual_hash": perceptual_hash,
    }
    asset.save(update_fields=("metadata", "updated_at"))
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
