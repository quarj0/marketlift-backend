from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from payments.providers.factory import payment_provider_enabled
from payments.tasks import sync_mercado_pago_order, sync_paystack_transaction
from payments.webhooks import valid_mercado_pago_signature, valid_paystack_signature


class MercadoPagoWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        if not getattr(settings, "MARKETLIFT_PAYMENTS_ENABLED", False):
            return Response({"detail": "Payments are not available yet."}, status=503)
        if not payment_provider_enabled("mercado_pago"):
            return Response({"detail": "Mercado Pago is not enabled."}, status=404)
        data_id = str(
            request.query_params.get("data.id")
            or (
                (request.data.get("data") or {}).get("id")
                if isinstance(request.data, dict)
                else ""
            )
            or ""
        )
        valid = valid_mercado_pago_signature(
            data_id=data_id,
            request_id=request.headers.get("x-request-id", ""),
            signature=request.headers.get("x-signature", ""),
            secret=getattr(settings, "MERCADO_PAGO_WEBHOOK_SECRET", ""),
        )
        if not valid:
            return Response({"detail": "Invalid webhook signature."}, status=401)

        try:
            sync_mercado_pago_order.delay(data_id)
        except Exception:
            return Response({"detail": "Webhook queue unavailable."}, status=503)
        return Response({"ok": True})


class PaystackWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        if not getattr(settings, "MARKETLIFT_PAYMENTS_ENABLED", False):
            return Response({"detail": "Payments are not available yet."}, status=503)
        if not payment_provider_enabled("paystack"):
            return Response({"detail": "Paystack is not enabled."}, status=404)

        secret = getattr(settings, "PAYSTACK_SECRET_KEY", "")
        if not valid_paystack_signature(
            body=request.body,
            signature=request.headers.get("x-paystack-signature", ""),
            secret=secret,
        ):
            return Response({"detail": "Invalid webhook signature."}, status=401)

        payload = request.data if isinstance(request.data, dict) else {}
        event = str(payload.get("event") or "")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        reference = str(data.get("reference") or "").strip()

        # Marketlift service value is fulfilled only after our worker re-verifies
        # the transaction directly with Paystack. Unknown events can be acknowledged.
        if event == "charge.success" and reference:
            try:
                sync_paystack_transaction.delay(reference)
            except Exception:
                return Response({"detail": "Webhook queue unavailable."}, status=503)
        return Response({"ok": True})
