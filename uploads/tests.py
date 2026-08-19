import io
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from uploads.models import UploadAsset
from uploads.services import (
    claim_upload,
    complete_upload,
    prepare_upload,
    store_proxy_upload,
)

User = get_user_model()


@override_settings(MARKETLIFT_LOCAL_UPLOAD_ROOT="/tmp/marketlift-test-uploads")
class UploadServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="upload@example.com", full_name="Upload User", password="secret123"
        )

    def test_prepare_store_complete_and_claim(self):
        payload = b"tiny-image"
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
        payload = b"tiny-image"
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


@override_settings(MARKETLIFT_LOCAL_UPLOAD_ROOT="/tmp/marketlift-listing-test-uploads")
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
        payload = b"listing-image"
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
            state="State",
            state_code="ST",
            city="City",
            image_upload_ids=[asset.id],
        )
        media = listing.media.select_related("upload").get()
        asset.refresh_from_db()
        self.assertEqual(media.upload_id, asset.id)
        self.assertEqual(media.content_url, asset.content_url)
        self.assertEqual(asset.status, UploadAsset.Status.ATTACHED)
