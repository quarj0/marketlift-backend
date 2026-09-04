import io
from PIL import Image
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from uploads.models import UploadAsset
from uploads.services import (
    claim_upload,
    complete_upload,
    prepare_upload,
    store_proxy_upload,
)

User = get_user_model()

LOCAL_UPLOAD_SETTINGS = {
    "MARKETLIFT_STORAGE_BACKENDS": {
        "default": "uploads.storage.local.LocalStorageBackend"
    },
    "MARKETLIFT_UPLOAD_STAGING_ALIAS": "default",
    "MARKETLIFT_UPLOAD_PURPOSE_ALIASES": {
        "listing_image": "default",
        "message_image": "default",
    },
}


def jpeg_bytes(*, width=4, height=4):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="JPEG")
    return buf.getvalue()


@override_settings(
    **LOCAL_UPLOAD_SETTINGS,
    MARKETLIFT_LOCAL_UPLOAD_ROOT="/tmp/marketlift-test-uploads",
)
class UploadServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="upload@example.com", full_name="Upload User", password="secret123"
        )

    def test_prepare_store_complete_and_claim(self):
        payload = jpeg_bytes()
        asset, target = prepare_upload(
            user=self.user,
            purpose=UploadAsset.Purpose.MESSAGE_IMAGE,
            original_name="photo.jpg",
            mime_type="image/jpeg",
            size=len(payload),
        )
        self.assertEqual(target.method, "PUT")
        store_proxy_upload(
            asset=asset,
            user=self.user,
            stream=io.BytesIO(payload),
            content_type="image/jpeg",
            content_length=len(payload),
        )
        complete_upload(asset=asset, user=self.user)
        asset.refresh_from_db()
        self.assertEqual(asset.status, UploadAsset.Status.READY)
        claim_upload(
            asset=asset, user=self.user, purpose=UploadAsset.Purpose.MESSAGE_IMAGE
        )
        asset.refresh_from_db()
        self.assertEqual(asset.status, UploadAsset.Status.ATTACHED)

    def test_rejects_mismatched_purpose(self):
        payload = jpeg_bytes()
        asset, _ = prepare_upload(
            user=self.user,
            purpose=UploadAsset.Purpose.MESSAGE_IMAGE,
            original_name="photo.jpg",
            mime_type="image/jpeg",
            size=len(payload),
        )
        store_proxy_upload(
            asset=asset,
            user=self.user,
            stream=io.BytesIO(payload),
            content_type="image/jpeg",
            content_length=len(payload),
        )
        complete_upload(asset=asset, user=self.user)
        with self.assertRaisesMessage(Exception, "different purpose"):
            claim_upload(
                asset=asset, user=self.user, purpose=UploadAsset.Purpose.LISTING_IMAGE
            )


@override_settings(
    **LOCAL_UPLOAD_SETTINGS,
    MARKETLIFT_LOCAL_UPLOAD_ROOT="/tmp/marketlift-listing-test-uploads",
)
class ListingUploadIntegrationTests(TestCase):
    def test_listing_can_claim_prepared_image_upload(self):
        from categories.models import Category
        from listings.services import create_listing
        from sellers.models import SellerProfile

        user = User.objects.create_user(
            email="seller-upload@example.com",
            full_name="Seller Upload",
            password="secret123",
        )
        seller = SellerProfile.objects.create(user=user)
        category = Category.objects.create(
            slug="upload-test",
            name="Upload Test",
            active=True,
            pricing_mode="optional",
            condition_enabled=False,
            condition_required=False,
        )
        payload = jpeg_bytes(width=400, height=400)
        asset, _ = prepare_upload(
            user=user,
            purpose=UploadAsset.Purpose.LISTING_IMAGE,
            original_name="listing.jpg",
            mime_type="image/jpeg",
            size=len(payload),
        )
        store_proxy_upload(
            asset=asset,
            user=user,
            stream=io.BytesIO(payload),
            content_type="image/jpeg",
            content_length=len(payload),
        )
        complete_upload(asset=asset, user=user)

        listing = create_listing(
            seller=seller,
            category=category,
            title="Listing with upload",
            description="Description",
            state="São Paulo",
            state_code="SP",
            city="São Paulo",
            image_upload_ids=[asset.id],
        )
        media = listing.media.select_related("upload").get()
        asset.refresh_from_db()
        self.assertEqual(media.upload_id, asset.id)
        self.assertEqual(media.content_url, asset.preferred_image_url("detail"))
        self.assertEqual(asset.status, UploadAsset.Status.ATTACHED)


@override_settings(
    MARKETLIFT_STORAGE_BUCKETS={
        "temp": "marketlift-temp",
        "public": "marketlift-public",
    },
    MARKETLIFT_PUBLIC_STORAGE_ALIAS="public",
    MARKETLIFT_PUBLIC_ASSET_BASE_URL="",
    MARKETLIFT_PRESIGNED_UPLOAD_TTL_SECONDS=900,
    MARKETLIFT_PRESIGNED_DOWNLOAD_TTL_SECONDS=300,
    MARKETLIFT_S3_ENDPOINT_URL="https://account.example.r2.cloudflarestorage.com",
    MARKETLIFT_S3_ACCESS_KEY_ID="test-access-key",
    MARKETLIFT_S3_SECRET_ACCESS_KEY="test-secret-key",
    MARKETLIFT_S3_REGION="auto",
)
class S3CompatibleStorageBackendTests(SimpleTestCase):
    def _asset(self, *, key="listing_image/user/example.jpg", mime="image/jpeg"):
        class Asset:
            object_key = key
            mime_type = mime

        return Asset()

    def _response(self, status=200, *, content=b"", headers=None, method="GET"):
        import httpx

        request = httpx.Request(
            method,
            "https://account.example.r2.cloudflarestorage.com/marketlift-public/example",
        )
        return httpx.Response(
            status,
            request=request,
            content=content,
            headers=headers or {},
        )

    def test_prepare_upload_targets_the_logical_bucket(self):
        from urllib.parse import parse_qs, urlsplit
        from uploads.storage.s3 import S3CompatibleStorageBackend

        backend = S3CompatibleStorageBackend(alias="temp")
        target = backend.prepare_upload(self._asset())
        parsed = urlsplit(target.url)
        query = parse_qs(parsed.query)

        self.assertEqual(target.method, "PUT")
        self.assertEqual(target.headers, {"Content-Type": "image/jpeg"})
        self.assertEqual(
            parsed.path,
            "/marketlift-temp/listing_image/user/example.jpg",
        )
        self.assertEqual(query["X-Amz-Algorithm"], ["AWS4-HMAC-SHA256"])
        self.assertEqual(query["X-Amz-Expires"], ["900"])
        self.assertEqual(query["X-Amz-SignedHeaders"], ["content-type;host"])
        self.assertIn("X-Amz-Signature", query)

    def test_store_read_stat_and_delete_stay_on_the_selected_bucket(self):
        from unittest.mock import patch
        from uploads.storage.s3 import S3CompatibleStorageBackend

        backend = S3CompatibleStorageBackend(alias="public")
        asset = self._asset()
        responses = [
            self._response(200, method="PUT"),
            self._response(
                200,
                headers={
                    "content-length": "5",
                    "content-type": "image/jpeg",
                    "x-amz-meta-sha256": "abc123",
                },
                method="HEAD",
            ),
            self._response(200, content=b"hello", method="GET"),
            self._response(204, method="DELETE"),
        ]
        with patch(
            "uploads.storage.s3.httpx.request", side_effect=responses
        ) as request:
            info = backend.store(asset, io.BytesIO(b"hello"))
            stat = backend.stat(asset)
            opened = backend.open(asset).read()
            backend.delete(asset)

        self.assertEqual(info.size, 5)
        self.assertEqual(stat.size, 5)
        self.assertEqual(opened, b"hello")
        urls = [call.args[1] for call in request.call_args_list]
        self.assertTrue(urls)
        self.assertTrue(all("/marketlift-public/" in url for url in urls))
        put_headers = request.call_args_list[0].kwargs["headers"]
        self.assertEqual(
            put_headers["cache-control"], "public, max-age=31536000, immutable"
        )
        self.assertIn("authorization", put_headers)

    def test_public_base_url_avoids_signed_get_url(self):
        from uploads.storage.s3 import S3CompatibleStorageBackend

        backend = S3CompatibleStorageBackend(alias="public")
        asset = self._asset(key="seller avatars/user one/avatar.jpg")
        with override_settings(
            MARKETLIFT_PUBLIC_ASSET_BASE_URL="https://assets.example.com"
        ):
            url = backend.access_url(asset)
        self.assertEqual(
            url,
            "https://assets.example.com/seller%20avatars/user%20one/avatar.jpg",
        )
