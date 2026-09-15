from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.services import update_profile


class PartialProfileUpdateTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            email="partial-profile@example.com",
            password="testpass123",
            full_name="Original Name",
            phone="+5511999999999",
        )

    def test_updating_one_profile_field_preserves_unsubmitted_fields(self):
        original_email = self.user.email
        original_name = self.user.full_name
        original_phone = self.user.phone
        original_country = self.user.country_code

        updated = update_profile(
            user=self.user,
            data={"bio": "Updated bio only"},
        )
        updated.refresh_from_db()

        self.assertEqual(updated.bio, "Updated bio only")
        self.assertEqual(updated.email, original_email)
        self.assertEqual(updated.full_name, original_name)
        self.assertEqual(updated.phone, original_phone)
        self.assertEqual(updated.country_code, original_country)

    def test_updating_name_does_not_require_location_fields(self):
        updated = update_profile(
            user=self.user,
            data={"full_name": "Changed Name"},
        )
        updated.refresh_from_db()

        self.assertEqual(updated.full_name, "Changed Name")
        self.assertEqual(updated.state, "")
        self.assertEqual(updated.city, "")
