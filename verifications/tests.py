from datetime import date
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from sellers.models import SellerProfile
from .models import VerificationSubmission
from .services import approve_verification, reject_verification, submit_verification


class VerificationTests(TestCase):
    def setUp(self):
        U = get_user_model()
        self.user = U.objects.create_user(
            email="seller@example.com", password="testpass123", full_name="Seller One"
        )
        self.staff = U.objects.create_user(
            email="admin@example.com",
            password="testpass123",
            full_name="Admin",
            is_staff=True,
        )
        self.seller = SellerProfile.objects.create(user=self.user, display_name="Shop")

    def test_cpf_is_not_stored_plaintext_and_approval_is_final(self):
        v = submit_verification(
            seller=self.seller,
            cpf="529.982.247-25",
            legal_name="Seller One",
            birth_date=date(1992, 4, 15),
        )
        self.assertEqual(v.cpf_masked, "***.***.***-25")
        self.assertNotIn("52998224725", v.cpf_digest)
        approve_verification(verification=v, actor=self.staff, note="matched")
        self.seller.refresh_from_db()
        self.assertTrue(self.seller.verified)
        with self.assertRaises(ValidationError):
            reject_verification(verification=v, actor=self.staff, note="no")

    def test_rejected_seller_may_submit_new_attempt(self):
        v = submit_verification(
            seller=self.seller,
            cpf="52998224725",
            legal_name="Seller One",
            birth_date=date(1992, 4, 15),
        )
        reject_verification(verification=v, actor=self.staff, note="image mismatch")
        again = submit_verification(
            seller=self.seller,
            cpf="52998224725",
            legal_name="Seller One",
            birth_date=date(1992, 4, 15),
        )
        self.assertEqual(again.status, VerificationSubmission.Status.PENDING)
