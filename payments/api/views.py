from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from payments.tasks import sync_mercado_pago_order
from payments.webhooks import valid_mercado_pago_signature


class MercadoPagoWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        if not getattr(settings, "MARKETLIFT_PAYMENTS_ENABLED", False):
            return Response({"detail": "Payments are not available yet."}, status=503)
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
            # A non-2xx response allows the provider to retry instead of silently
            # losing an event when the worker/broker is temporarily unavailable.
            return Response({"detail": "Webhook queue unavailable."}, status=503)
        return Response({"ok": True})
