"""Sampled anonymous web vitals. Client measurements are untrusted diagnostics."""

import logging
import math
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from marketlift.security.rate_limit import enforce_rate_limit

logger = logging.getLogger("marketlift.web_vitals")
ROUTES = {
    "/",
    "/search",
    "/register",
    "/login",
    "/help",
    "/help/report",
    "/listing/:slug",
    "/category/:slug",
    "/seller/:id",
    "/other",
}


class WebVitalsView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        enforce_rate_limit(request, "web-vitals", limit=30, window=60)
        if not isinstance(request.data, dict):
            raise ValidationError("Expected a metric object.")
        name = request.data.get("name")
        route = request.data.get("route")
        if not isinstance(name, str) or not isinstance(route, str):
            raise ValidationError("Invalid metric.")
        try:
            value = float(request.data.get("value"))
        except (TypeError, ValueError) as exc:
            raise ValidationError("Invalid metric value.") from exc
        if (
            name not in {"CLS", "LCP", "INP", "TTFB", "FCP"}
            or route not in ROUTES
            or not math.isfinite(value)
            or not 0 <= value <= 60000
        ):
            raise ValidationError("Invalid metric.")
        logger.info("web_vital name=%s route=%s value=%.3f", name, route, value)
        return Response(status=204)
