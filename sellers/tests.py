from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from sellers.models import SellerFollow, SellerProfile
from sellers.services import follow_seller


class SellerFollowSecurityTests(TestCase):
    def test_user_cannot_follow_own_seller_profile(self):
        User = get_user_model()
        user = User.objects.create_user(
            email="self-follow@example.com",
            full_name="Self Follow",
            password="Secure-Test-482!",
        )
        seller = SellerProfile.objects.create(user=user, display_name="Self Follow")

        with self.assertRaisesMessage(
            ValidationError, "You cannot follow your own seller profile."
        ):
            follow_seller(user=user, seller=seller)

        self.assertFalse(
            SellerFollow.objects.filter(follower=user, seller=seller).exists()
        )
