from __future__ import annotations

from html import unescape
from io import BytesIO
from pathlib import Path
import json
import re
import time

import httpx
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count

from categories.models import Category
from uploads.models import UploadAsset
from uploads.services import claim_upload, complete_upload, prepare_upload, retire_upload
from uploads.storage import get_storage_backend


GENERIC_SLUG_PREFIXES = ("other-",)
BAD_TITLE_WORDS = {
    "logo", "icon", "diagram", "map", "flag", "coat of arms", "poster",
    "drawing", "illustration", "symbol", "chart", "screenshot", "svg",
    "painting", "stamp", "sign",
}
ALLOWED_LICENSE_PREFIXES = (
    "cc0",
    "cc by",
    "cc-by",
    "cc by-sa",
    "cc-by-sa",
    "public domain",
    "pd",
)


def _meta(info: dict, key: str) -> str:
    value = (info.get("extmetadata") or {}).get(key) or {}
    return unescape(str(value.get("value") or "")).strip()


def _clean_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", unescape(value or "")).strip()


class Command(BaseCommand):
    help = (
        "Give meaningful Marketlift subcategories distinct real images. "
        "Existing unique category images are preserved; inherited/shared "
        "images are replaced with category-specific Wikimedia Commons photos."
    )

    def add_arguments(self, parser):
        parser.add_argument("--owner-email")
        parser.add_argument(
            "--category",
            action="append",
            help="Only process this category slug. Repeat for multiple categories.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Replace even an existing unique child image.",
        )
        parser.add_argument(
            "--audit-only",
            action="store_true",
            help="Show what would be replaced without downloading or saving.",
        )

    def _owner(self, email: str | None):
        User = get_user_model()
        qs = User.objects.filter(is_active=True)
        if email:
            user = qs.filter(email__iexact=email.strip()).first()
            if user is None:
                raise CommandError(f"No active user exists for {email}.")
            return user
        user = qs.filter(is_superuser=True).order_by("date_joined").first()
        if user is None:
            user = qs.filter(is_staff=True).order_by("date_joined").first()
        if user is None:
            raise CommandError(
                "No active staff user exists. Pass --owner-email."
            )
        return user

    def _query_map(self):
        path = (
            Path(__file__).resolve().parents[2]
            / "data"
            / "subcategory_image_queries.json"
        )
        return json.loads(path.read_text(encoding="utf-8"))

    def _needs_replacement(self, category: Category, *, force: bool) -> bool:
        if force:
            return True
        if category.image_upload_id is None:
            return True

        # The image is inherited/shared when another active category references
        # the same UploadAsset. Those are exactly the duplicates we want to fix.
        return Category.objects.filter(
            active=True,
            image_upload_id=category.image_upload_id,
        ).exclude(pk=category.pk).exists()

    def _search_commons(
        self,
        client: httpx.Client,
        *,
        query: str,
        used_sources: set[str],
    ) -> dict | None:
        response = client.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "generator": "search",
                "gsrsearch": query,
                "gsrnamespace": 6,
                "gsrlimit": 20,
                "prop": "imageinfo",
                "iiprop": "url|mime|size|extmetadata",
                "iiurlwidth": 640,
                "format": "json",
                "formatversion": 2,
            },
        )
        response.raise_for_status()
        pages = ((response.json().get("query") or {}).get("pages") or [])

        candidates = []
        for page in pages:
            title = str(page.get("title") or "")
            title_lower = title.casefold()
            if any(word in title_lower for word in BAD_TITLE_WORDS):
                continue

            infos = page.get("imageinfo") or []
            if not infos:
                continue
            info = infos[0]

            mime = str(info.get("mime") or "").lower()
            if mime not in {"image/jpeg", "image/png", "image/webp"}:
                continue

            width = int(info.get("width") or 0)
            height = int(info.get("height") or 0)
            if width < 700 or height < 400:
                continue

            aspect = width / max(height, 1)
            if aspect < 0.8 or aspect > 2.5:
                continue

            license_name = _meta(info, "LicenseShortName").casefold()
            if license_name and not license_name.startswith(ALLOWED_LICENSE_PREFIXES):
                continue

            source = str(info.get("descriptionurl") or info.get("url") or "")
            if not source or source in used_sources:
                continue

            thumb = str(info.get("thumburl") or "")
            if not thumb or "thumbnail_unscaled" in thumb:
                continue

            candidates.append(
                {
                    "title": title,
                    "download_url": thumb,
                    "source_url": source,
                    "mime_type": mime,
                    "artist": _clean_html(_meta(info, "Artist")),
                    "credit": _clean_html(_meta(info, "Credit")),
                    "license": _meta(info, "LicenseShortName") or "Wikimedia Commons",
                    "license_url": _meta(info, "LicenseUrl"),
                    "width": width,
                    "height": height,
                }
            )

        return candidates[0] if candidates else None

    def _store(
        self,
        *,
        client: httpx.Client,
        category: Category,
        candidate: dict,
        owner,
    ):
        response = None
        for attempt in range(4):
            response = client.get(candidate["download_url"])
            if response.status_code != 429:
                response.raise_for_status()
                break
            retry_after = response.headers.get("retry-after")
            try:
                delay = float(retry_after) if retry_after else (2 ** attempt)
            except (TypeError, ValueError):
                delay = 2 ** attempt
            time.sleep(max(1.0, min(delay, 12.0)))
        else:
            raise CommandError(
                f"{category.slug}: Wikimedia rate limit persisted after retries."
            )

        payload = response.content
        content_type = (
            response.headers.get("content-type", "")
            .split(";", 1)[0]
            .strip()
            .lower()
        )
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            content_type = candidate["mime_type"]

        if len(payload) <= 0 or len(payload) > 5 * 1024 * 1024:
            raise CommandError(
                f"{category.slug}: downloaded image is outside Marketlift limits."
            )

        extension = {
            "image/jpeg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
        }.get(content_type, "jpg")

        old_asset = category.image_upload

        with transaction.atomic():
            asset, _ = prepare_upload(
                user=owner,
                purpose=UploadAsset.Purpose.CATEGORY_IMAGE,
                original_name=f"{category.slug}-commons.{extension}",
                mime_type=content_type,
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
                "source_provider": "Wikimedia Commons",
                "source_url": candidate["source_url"],
                "source_title": candidate["title"],
                "artist": candidate["artist"],
                "credit": candidate["credit"],
                "license": candidate["license"],
                "license_url": candidate["license_url"],
                "seeded_for": f"category:{category.slug}",
                "category_specific": True,
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

        if (
            old_asset is not None
            and old_asset.pk != asset.pk
            and not Category.objects.filter(image_upload=old_asset).exists()
        ):
            retire_upload(asset=old_asset)

        return asset

    def handle(self, *args, **options):
        query_map = self._query_map()
        only = set(options["category"] or [])
        force = options["force"]
        audit_only = options["audit_only"]
        owner = None if audit_only else self._owner(options["owner_email"])

        qs = (
            Category.objects.select_related("parent", "image_upload")
            .filter(active=True, parent__isnull=False)
            .order_by("parent__sort_order", "sort_order", "name")
        )
        if only:
            qs = qs.filter(slug__in=only)

        categories = list(qs)
        used_sources = set(
            UploadAsset.objects.filter(
                purpose=UploadAsset.Purpose.CATEGORY_IMAGE,
                status=UploadAsset.Status.ATTACHED,
            )
            .exclude(metadata__source_url="")
            .values_list("metadata__source_url", flat=True)
        )

        to_replace = []
        preserved = []
        generic = []

        for category in categories:
            if category.slug.startswith(GENERIC_SLUG_PREFIXES):
                generic.append(category.slug)
                continue
            if self._needs_replacement(category, force=force):
                to_replace.append(category)
            else:
                preserved.append(category.slug)

        self.stdout.write(
            f"{len(categories)} active descendants checked; "
            f"{len(to_replace)} need distinct images; "
            f"{len(preserved)} already have unique images; "
            f"{len(generic)} generic fallback categories skipped."
        )

        if audit_only:
            for category in to_replace:
                query = query_map.get(
                    category.slug,
                    f"{category.name} photograph",
                )
                self.stdout.write(f"WOULD REPLACE {category.slug}: {query}")
            return

        client = httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(30.0),
            headers={
                "User-Agent": (
                    "MarketliftCategoryVisualSeeder/2.0 "
                    "(category image curation)"
                ),
                "Accept": "application/json,image/*;q=0.9,*/*;q=0.2",
            },
        )
        succeeded = 0
        failed = []

        try:
            for category in to_replace:
                query = query_map.get(
                    category.slug,
                    f"{category.name} photograph",
                )
                try:
                    candidate = self._search_commons(
                        client,
                        query=query,
                        used_sources=used_sources,
                    )
                    if candidate is None:
                        failed.append(
                            (category.slug, "no suitable licensed photo found")
                        )
                        self.stdout.write(
                            self.style.WARNING(
                                f"{category.slug}: no suitable photo found; "
                                "existing fallback kept."
                            )
                        )
                        continue

                    self._store(
                        client=client,
                        category=category,
                        candidate=candidate,
                        owner=owner,
                    )
                    used_sources.add(candidate["source_url"])
                    succeeded += 1
                    time.sleep(0.75)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"{category.slug}: {candidate['title']}"
                        )
                    )
                except Exception as exc:
                    failed.append((category.slug, str(exc)))
                    self.stdout.write(
                        self.style.WARNING(
                            f"{category.slug}: {exc}; existing fallback kept."
                        )
                    )
        finally:
            client.close()

        self.stdout.write(
            self.style.SUCCESS(
                f"Distinct category images complete: {succeeded} updated, "
                f"{len(failed)} retained their existing fallback."
            )
        )
        if failed:
            self.stdout.write(
                self.style.WARNING(
                    "Review these in Admin: "
                    + ", ".join(slug for slug, _ in failed)
                )
            )
