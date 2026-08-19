from django.test import TestCase

from accounts.models import AccountSettings, User
from sellers.models import SellerProfile


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
