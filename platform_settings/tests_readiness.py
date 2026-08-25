from django.test import SimpleTestCase, override_settings

from platform_settings.models import Market
from platform_settings.readiness import (
    identity_provider_readiness,
    payment_provider_readiness,
)


class ProviderReadinessTests(SimpleTestCase):
    def _market(self, **overrides):
        values = {
            "code": "GH",
            "country_name": "Ghana",
            "payment_provider": "paystack",
            "payment_methods": ["card", "mobile_money"],
            "identity_provider": "disabled",
        }
        values.update(overrides)
        return Market(**values)

    @override_settings(PAYSTACK_SECRET_KEY="sk_test_ready", PAYSTACK_CALLBACK_URL="")
    def test_paystack_requires_callback_url(self):
        ready, message = payment_provider_readiness(self._market())
        self.assertFalse(ready)
        self.assertIn("callback", message.lower())

    @override_settings(
        PAYSTACK_SECRET_KEY="sk_test_ready",
        PAYSTACK_CALLBACK_URL="https://marketlift.example/selling/payments",
    )
    def test_paystack_is_ready_with_secret_and_callback(self):
        ready, _ = payment_provider_readiness(self._market())
        self.assertTrue(ready)

    @override_settings(
        MERCADO_PAGO_ACCESS_TOKEN="APP_USR-test",
        MERCADO_PAGO_WEBHOOK_SECRET="webhook-secret",
    )
    def test_mercado_pago_card_stays_blocked_without_tokenization_adapter(self):
        market = self._market(
            code="BR",
            country_name="Brazil",
            payment_provider="mercado_pago",
            payment_methods=["pix", "card", "boleto"],
        )
        ready, message = payment_provider_readiness(market)
        self.assertFalse(ready)
        self.assertIn("tokenization", message.lower())

    @override_settings(
        MERCADO_PAGO_ACCESS_TOKEN="APP_USR-test",
        MERCADO_PAGO_WEBHOOK_SECRET="webhook-secret",
    )
    def test_mercado_pago_pix_and_boleto_can_be_ready(self):
        market = self._market(
            code="BR",
            country_name="Brazil",
            payment_provider="mercado_pago",
            payment_methods=["pix", "boleto"],
        )
        ready, _ = payment_provider_readiness(market)
        self.assertTrue(ready)

    @override_settings(
        MARKETLIFT_IDENTITY_VERIFICATION_ENABLED=True,
        MARKETLIFT_IDENTITY_PROVIDER_READY=True,
    )
    def test_identity_adapter_requires_external_provider_key(self):
        ready, _ = identity_provider_readiness(
            self._market(identity_provider="disabled")
        )
        self.assertFalse(ready)
        ready, _ = identity_provider_readiness(
            self._market(identity_provider="ghana_card_provider")
        )
        self.assertTrue(ready)
