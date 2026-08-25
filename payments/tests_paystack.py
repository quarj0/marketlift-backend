from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from marketlift.markets.profiles import get_market_profile
from payments.providers.paystack import PaystackProvider
from payments.webhooks import valid_paystack_signature

GH = get_market_profile("GH")


@override_settings(
    MARKETLIFT_MARKET_CODE="GH",
    MARKETLIFT_MARKET=GH,
    MARKETLIFT_ENABLED_MARKETS=(GH,),
    MARKETLIFT_SUPPORTED_COUNTRY_CODES=("GH",),
    PAYSTACK_SECRET_KEY="sk_test_marketlift",
    PAYSTACK_API_BASE_URL="https://api.paystack.co",
)
class PaystackProviderTests(SimpleTestCase):
    @patch("payments.providers.paystack.httpx.Client")
    def test_initialize_uses_subunits_and_marketlift_only_metadata(self, client_class):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "status": True,
            "message": "Authorization URL created",
            "data": {
                "authorization_url": "https://checkout.paystack.com/test",
                "access_code": "abc",
                "reference": "ML-REF",
            },
        }
        client = client_class.return_value.__enter__.return_value
        client.request.return_value = response

        payment = SimpleNamespace(
            id="payment-1",
            amount=Decimal("123.45"),
            currency="GHS",
            reference="ML-REF",
            method="mobile_money",
            purpose="subscription",
            seller_id="seller-1",
            user=SimpleNamespace(email="seller@example.com"),
        )
        result = PaystackProvider().create_order(
            payment=payment,
            payer={"email": "seller@example.com"},
        )

        _, url = client.request.call_args.args
        payload = client.request.call_args.kwargs["json"]
        self.assertEqual(url, "https://api.paystack.co/transaction/initialize")
        self.assertEqual(payload["amount"], "12345")
        self.assertEqual(payload["currency"], "GHS")
        self.assertEqual(payload["channels"], ["mobile_money"])
        import json

        metadata = json.loads(payload["metadata"])
        self.assertEqual(metadata["marketlift_payment_id"], "payment-1")
        self.assertNotIn("subaccount", payload)
        self.assertEqual(result.order_id, "ML-REF")
        self.assertEqual(result.amount, Decimal("123.45"))

    @patch("payments.providers.paystack.httpx.Client")
    def test_verify_converts_subunit_amount_back_to_major_currency(self, client_class):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "status": True,
            "data": {
                "id": 987,
                "reference": "ML-REF",
                "status": "success",
                "gateway_response": "Successful",
                "amount": 12345,
                "currency": "GHS",
                "channel": "mobile_money",
            },
        }
        client = client_class.return_value.__enter__.return_value
        client.request.return_value = response

        result = PaystackProvider().get_order("ML-REF")
        self.assertEqual(result.status, "success")
        self.assertEqual(result.amount, Decimal("123.45"))
        self.assertEqual(result.currency, "GHS")

    def test_webhook_signature_uses_sha512(self):
        import hashlib
        import hmac

        body = b'{"event":"charge.success","data":{"reference":"ML-REF"}}'
        signature = hmac.new(b"sk_test_marketlift", body, hashlib.sha512).hexdigest()
        self.assertTrue(
            valid_paystack_signature(
                body=body, signature=signature, secret="sk_test_marketlift"
            )
        )
        self.assertFalse(
            valid_paystack_signature(
                body=body, signature="invalid", secret="sk_test_marketlift"
            )
        )


class PaymentProviderRoutingTests(SimpleTestCase):
    @override_settings(
        MARKETLIFT_PAYMENT_PROVIDER="auto",
        MARKETLIFT_MARKET_CODE="GH",
        MARKETLIFT_MARKET=GH,
        MARKETLIFT_ENABLED_MARKETS=(GH,),
        MARKETLIFT_SUPPORTED_COUNTRY_CODES=("GH",),
    )
    def test_auto_provider_routes_ghana_to_paystack(self):
        from payments.providers.factory import get_payment_provider

        self.assertEqual(get_payment_provider(country_code="GH").name, "paystack")

    @override_settings(
        MARKETLIFT_PAYMENT_PROVIDER="auto",
        MARKETLIFT_MARKET_CODE="BR",
        MARKETLIFT_MARKET=get_market_profile("BR"),
        MARKETLIFT_ENABLED_MARKETS=(get_market_profile("BR"), GH),
        MARKETLIFT_SUPPORTED_COUNTRY_CODES=("BR", "GH"),
    )
    def test_auto_provider_can_route_mixed_enabled_markets(self):
        from payments.providers.factory import get_payment_provider

        self.assertEqual(get_payment_provider(country_code="BR").name, "mercado_pago")
        self.assertEqual(get_payment_provider(country_code="GH").name, "paystack")
