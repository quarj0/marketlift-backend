from marketlift.markets.profiles import get_market_profile
from datetime import date
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from sellers.models import SellerProfile
from .models import VerificationSubmission
from .services import (
    approve_verification,
    reject_verification,
    require_cpf_verification_enabled,
    submit_verification,
)


@override_settings(MARKETLIFT_CPF_VERIFICATION_ENABLED=False)
class CpfVerificationReleaseGateTests(SimpleTestCase):
    def test_cpf_verification_is_dormant_by_default(self):
        with self.assertRaisesMessage(ValidationError, "not available yet"):
            require_cpf_verification_enabled()


@override_settings(MARKETLIFT_CPF_VERIFICATION_ENABLED=True)
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


class MultiMarketIdentityNormalizationTests(SimpleTestCase):
    @override_settings(
        MARKETLIFT_MARKET_COUNTRY_CODE="GH",
        MARKETLIFT_SUPPORTED_COUNTRY_CODES=("GH",),
        MARKETLIFT_ENABLED_MARKETS=(get_market_profile("GH"),),
    )
    def test_ghana_card_is_normalized_without_storing_formatting(self):
        from verifications.services import normalize_identity_number, mask_identity

        value = normalize_identity_number("GHA-123456789-0", country_code="GH")
        self.assertEqual(value, "GHA1234567890")
        self.assertEqual(mask_identity(value, country_code="GH"), "••••7890")

    @override_settings(
        MARKETLIFT_MARKET_COUNTRY_CODE="BR",
        MARKETLIFT_SUPPORTED_COUNTRY_CODES=("BR",),
        MARKETLIFT_ENABLED_MARKETS=(get_market_profile("BR"),),
    )
    def test_brazil_cpf_validator_remains_available(self):
        from verifications.services import normalize_identity_number

        # Well-known mathematically valid CPF used only as a checksum test value.
        self.assertEqual(
            normalize_identity_number("529.982.247-25", country_code="BR"),
            "52998224725",
        )
