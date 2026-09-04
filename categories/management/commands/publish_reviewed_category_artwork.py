from __future__ import annotations

from io import BytesIO
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from uploads.storage import get_storage_backend


class Command(BaseCommand):
    help = (
        "Audit or publish the visually reviewed Marketlift category artwork set "
        "directly to the configured public object-storage bucket."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-dir",
            required=True,
            help="Directory containing the reviewed <artwork-key>.webp files.",
        )
        parser.add_argument(
            "--prefix",
            default="categories/photographic/v1",
            help="Public object-key prefix (default: categories/photographic/v1).",
        )
        parser.add_argument(
            "--audit-only",
            action="store_true",
            help="Validate every source file and destination without uploading.",
        )

    def _manifest(self) -> dict[str, list[str]]:
        path = (
            Path(__file__).resolve().parents[2]
            / "data"
            / "reviewed_category_artwork.json"
        )
        return json.loads(path.read_text(encoding="utf-8"))

    def handle(self, *args, **options):
        source_dir = Path(options["source_dir"]).expanduser().resolve()
        if not source_dir.is_dir():
            raise CommandError(f"Artwork directory does not exist: {source_dir}")

        prefix = str(PurePosixPath(options["prefix"].strip().strip("/")))
        if prefix in {"", "."} or ".." in PurePosixPath(prefix).parts:
            raise CommandError("The destination prefix is invalid.")

        manifest = self._manifest()
        files: dict[str, tuple[Path, bytes]] = {}
        for artwork_key in manifest:
            path = source_dir / f"{artwork_key}.webp"
            if not path.is_file():
                raise CommandError(f"Missing reviewed artwork: {path}")
            payload = path.read_bytes()
            if not payload or len(payload) > 5 * 1024 * 1024:
                raise CommandError(f"Artwork size is invalid: {path.name}")
            if not payload.startswith(b"RIFF") or payload[8:12] != b"WEBP":
                raise CommandError(f"Artwork is not a WebP image: {path.name}")
            files[artwork_key] = (path, payload)

        public_base = settings.MARKETLIFT_PUBLIC_ASSET_BASE_URL.rstrip("/")
        if not public_base:
            raise CommandError("The public asset base URL is not configured.")

        self.stdout.write(
            f"Reviewed set: {len(files)} artwork files for "
            f"{sum(len(slugs) for slugs in manifest.values())} category mappings."
        )
        self.stdout.write(f"Destination: {public_base}/{prefix}/")
        if options["audit_only"]:
            self.stdout.write(self.style.SUCCESS("Audit passed; no objects were uploaded."))
            return

        backend = get_storage_backend(settings.MARKETLIFT_PUBLIC_STORAGE_ALIAS)
        for artwork_key, (path, payload) in files.items():
            asset = SimpleNamespace(
                object_key=f"{prefix}/{artwork_key}.webp",
                mime_type="image/webp",
            )
            stored = backend.store(
                asset,
                BytesIO(payload),
                content_length=len(payload),
            )
            if stored.size != len(payload):
                raise CommandError(f"Stored size mismatch for {path.name}.")
            self.stdout.write(
                self.style.SUCCESS(f"{artwork_key}: {public_base}/{asset.object_key}")
            )

        self.stdout.write(self.style.SUCCESS("Reviewed category artwork is published."))
