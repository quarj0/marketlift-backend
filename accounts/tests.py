from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from django.utils import timezone

from accounts.models import AccountSettings, User
from accounts.services import update_profile
from sellers.models import SellerProfile
from uploads.models import UploadAsset, UploadVariant


class UserModelTests(TestCase):
    def test_customer_account_does_not_require_seller_profile(self):
        user = User.objects.create_user(
            email="buyer@example.com",
            full_name="Buyer Example",
            password="StrongPassword123!",
        )

        self.assertEqual(user.email, "buyer@example.com")
        self.assertFalse(hasattr(user, "seller_profile"))

    def test_selling_is_activated_with_optional_seller_profile(self):
        user = User.objects.create_user(
            email="seller@example.com",
            full_name="Seller Example",
            password="StrongPassword123!",
        )
        seller = SellerProfile.objects.create(user=user)

        self.assertEqual(seller.user_id, user.id)
        self.assertEqual(user.seller_profile.id, seller.id)

    def test_account_settings_support_marketplace_defaults(self):
        user = User.objects.create_user(
            email="settings@example.com",
            full_name="Settings Example",
            password="StrongPassword123!",
        )
        settings = AccountSettings.objects.create(user=user)

        self.assertEqual(settings.language, AccountSettings.Language.PORTUGUESE_BRAZIL)
        self.assertEqual(settings.currency, "BRL")


class AccountSettingsMutationTests(TestCase):
    def test_partial_notification_setting_update_preserves_other_preferences(self):
        user = User.objects.create_user(
            email="notifications-settings@example.com",
            full_name="Notification Settings",
            password="StrongPassword123!",
        )
        settings = AccountSettings.objects.create(
            user=user,
            email_messages=False,
            email_listing_updates=True,
            push_messages=False,
            push_listing_updates=True,
        )
        self.client.force_login(user)

        response = self.client.post(
            "/graphql/",
            data={
                "query": """
                    mutation UpdateSettings($input: AccountSettingsInput!) {
                      updateMyAccountSettings(input: $input) {
                        emailMessages
                        emailListingUpdates
                        pushMessages
                        pushListingUpdates
                      }
                    }
                """,
                "variables": {"input": {"emailMessages": True}},
            },
            content_type="application/json",
        )

        payload = response.json()
        self.assertNotIn("errors", payload)
        result = payload["data"]["updateMyAccountSettings"]
        self.assertTrue(result["emailMessages"])
        self.assertTrue(result["emailListingUpdates"])
        self.assertFalse(result["pushMessages"])
        self.assertTrue(result["pushListingUpdates"])

        settings.refresh_from_db()
        self.assertTrue(settings.email_messages)
        self.assertTrue(settings.email_listing_updates)
        self.assertFalse(settings.push_messages)
        self.assertTrue(settings.push_listing_updates)


class AccountProfileLocationTests(TestCase):
    def test_profile_rejects_non_brazilian_state_code(self):
        user = User.objects.create_user(
            email="location@example.com",
            full_name="Location Example",
            password="StrongPassword123!",
        )
        with self.assertRaises(ValidationError):
            update_profile(
                user=user,
                data={
                    "state": "Georgia",
                    "state_code": "GA",
                    "city": "Accra",
                },
            )


class AccountAvatarTests(TestCase):
    def test_avatar_attachment_persists_absolute_api_url(self):
        user = User.objects.create_user(
            email="avatar@example.com",
            full_name="Avatar Example",
            password="StrongPassword123!",
        )
        asset = UploadAsset.objects.create(
            owner=user,
            purpose=UploadAsset.Purpose.AVATAR,
            status=UploadAsset.Status.READY,
            visibility=UploadAsset.Visibility.PUBLIC,
            storage_alias="default",
            object_key=f"avatar/{user.pk}/avatar.jpg",
            original_name="avatar.jpg",
            mime_type="image/jpeg",
            expected_size=256,
            actual_size=256,
            expires_at=timezone.now() + timedelta(hours=1),
            ready_at=timezone.now(),
        )
        UploadVariant.objects.create(
            asset=asset,
            kind="thumbnail",
            storage_alias="default",
            object_key=f"avatar/{user.pk}/avatar.thumbnail.webp",
            mime_type="image/webp",
            size=128,
            width=128,
            height=128,
        )
        request = RequestFactory().post(
            "/graphql/",
            secure=True,
            HTTP_HOST="api.marketlift.com.br",
        )

        updated = update_profile(
            user=user,
            data={},
            avatar_upload=asset,
            request=request,
        )

        self.assertEqual(
            updated.avatar_url,
            f"https://api.marketlift.com.br/api/v1/uploads/{asset.id}/variants/thumbnail/",
        )
        asset.refresh_from_db()
        self.assertEqual(asset.status, UploadAsset.Status.ATTACHED)
