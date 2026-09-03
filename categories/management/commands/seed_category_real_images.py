from __future__ import annotations

from io import BytesIO
from pathlib import Path
import json

import httpx
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from categories.models import Category
from uploads.models import UploadAsset
from uploads.services import claim_upload, complete_upload, prepare_upload, retire_upload
from uploads.storage import get_storage_backend


class Command(BaseCommand):
    help = (
        "Seed real stock-photo visuals for Marketlift root categories. "
        "Images are downloaded once and stored in Marketlift object storage."
    )

    def add_arguments(self, parser):
        parser.add_argument("--owner-email")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Replace existing category images. Default is to preserve them.",
        )

    def _owner(self, email: str | None):
        User = get_user_model()
        qs = User.objects.filter(is_active=True)
        if email:
            user = qs.filter(email__iexact=email.strip()).first()
            if not user:
                raise CommandError(f"No active user exists for {email}.")
            return user
        user = qs.filter(is_superuser=True).order_by("date_joined").first()
        if user is None:
            user = qs.filter(is_staff=True).order_by("date_joined").first()
        if user is None:
            raise CommandError(
                "No active staff user exists. Pass --owner-email with an active account."
            )
        return user

    def handle(self, *args, **options):
        source_path = (
            Path(__file__).resolve().parents[2] / "data" / "category_image_sources.json"
        )
        sources = json.loads(source_path.read_text(encoding="utf-8"))
        owner = self._owner(options["owner_email"])
        force = options["force"]

        client = httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(30.0),
            headers={
                "User-Agent": "MarketliftCategoryVisualSeeder/1.0",
                "Accept": "image/jpeg,image/*;q=0.8",
            },
        )
        try:
            for slug, info in sources.items():
                category = Category.objects.filter(slug=slug, parent__isnull=True).first()
                if category is None:
                    self.stdout.write(
                        self.style.WARNING(f"{slug}: root category does not exist; skipped.")
                    )
                    continue
                if category.image_upload_id and not force:
                    self.stdout.write(f"{slug}: already has an image; preserved.")
                    continue

                photo_id = int(info["photo_id"])
                download_url = (
                    f"https://images.pexels.com/photos/{photo_id}/"
                    f"pexels-photo-{photo_id}.jpeg"
                    "?auto=compress&cs=tinysrgb&w=1400&h=900&fit=crop"
                )
                response = client.get(download_url)
                response.raise_for_status()
                payload = response.content
                if len(payload) <= 0 or len(payload) > 5 * 1024 * 1024:
                    raise CommandError(
                        f"{slug}: downloaded image size is outside Marketlift limits."
                    )

                old_upload = category.image_upload
                with transaction.atomic():
                    asset, _ = prepare_upload(
                        user=owner,
                        purpose=UploadAsset.Purpose.CATEGORY_IMAGE,
                        original_name=f"{slug}-pexels-{photo_id}.jpg",
                        mime_type="image/jpeg",
                        size=len(payload),
                    )
                    stored = get_storage_backend(asset.storage_alias).store(
                        asset,
                        BytesIO(payload),
                        content_length=len(payload),
                    )
                    asset.actual_size = stored.size
                    asset.checksum_sha256 = stored.checksum_sha256
                    asset.metadata = {
                        **(asset.metadata or {}),
                        "source_provider": "Pexels",
                        "source_url": info["source_url"],
                        "photographer": info.get("photographer", ""),
                        "license": "Pexels License",
                        "license_url": "https://www.pexels.com/license/",
                        "seeded_for": f"category:{slug}",
                    }
                    asset.save(
                        update_fields=(
                            "actual_size",
                            "checksum_sha256",
                            "metadata",
                            "updated_at",
                        )
                    )
                    asset = complete_upload(asset=asset, user=owner)
                    asset = claim_upload(
                        asset=asset,
                        user=owner,
                        purpose=UploadAsset.Purpose.CATEGORY_IMAGE,
                    )
                    category.image_upload = asset
                    category.save(update_fields=("image_upload", "updated_at"))

                if old_upload and old_upload.pk != asset.pk:
                    retire_upload(asset=old_upload)

                self.stdout.write(
                    self.style.SUCCESS(
                        f"{slug}: real category image stored from Pexels photo {photo_id}."
                    )
                )
        finally:
            client.close()
