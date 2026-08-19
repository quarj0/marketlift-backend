import uuid
from django.conf import settings
from .base import BasePaymentProvider, ProviderResult


class MockPaymentProvider(BasePaymentProvider):
    name = "mock"

    def create_order(
        self, *, payment, payer: dict, card: dict | None = None
    ) -> ProviderResult:
        auto = getattr(settings, "PAYMENT_MOCK_AUTO_APPROVE", True)
        order_id = f"MOCKORD_{uuid.uuid4().hex[:20]}"
        payment_id = f"MOCKPAY_{uuid.uuid4().hex[:20]}"
        status = "processed" if auto else "action_required"
        detail = (
            "accredited"
            if auto
            else ("waiting_transfer" if payment.method == "pix" else "waiting_payment")
        )
        data = {}
        if payment.method == "pix":
            data = {
                "ticket_url": f"https://example.invalid/pix/{order_id}",
                "qr_code": f"MARKETLIFT-PIX-{payment.reference}",
                "qr_code_base64": "",
            }
        elif payment.method == "boleto":
            data = {
                "ticket_url": f"https://example.invalid/boleto/{order_id}",
                "barcode_content": "34191.79001 01043.510047 91020.150008 1 00000000000000",
            }
        return ProviderResult(
            order_id=order_id,
            payment_id=payment_id,
            status=status,
            status_detail=detail,
            checkout_data=data,
        )

    def get_order(self, order_id: str) -> ProviderResult:
        return ProviderResult(
            order_id=order_id, status="processed", status_detail="accredited"
        )
