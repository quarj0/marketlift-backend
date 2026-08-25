from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.cache import cache
from django.db import connection
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import HTTP_503_SERVICE_UNAVAILABLE
from django.conf import settings
from marketlift.markets.service import (
    active_market_profile,
    enabled_market_profiles,
    identity_provider_for_country_code,
)


@api_view(["GET"])
@permission_classes([AllowAny])
def market_profile(request):
    """Public deployment capabilities used to configure marketplace frontends."""

    active = active_market_profile()
    enabled = enabled_market_profiles()
    return Response(
        {
            "active": active.as_public_dict(),
            "enabledMarkets": [profile.as_public_dict() for profile in enabled],
            "payments": {
                "enabled": bool(settings.MARKETLIFT_PAYMENTS_ENABLED),
                "provider": active.default_payment_provider,
                "methods": list(active.payment_methods),
            },
            "identityVerification": {
                "enabled": bool(
                    getattr(settings, "MARKETLIFT_IDENTITY_VERIFICATION_ENABLED", False)
                ),
                "provider": identity_provider_for_country_code(active.country_code),
                "label": active.identity_label,
                "key": active.identity_key,
            },
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    return Response({"status": "ok", "service": "marketlift"})


@api_view(["GET"])
@permission_classes([AllowAny])
def readiness(request):
    checks: dict[str, str] = {}

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"

    try:
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')"
                )
                checks["search"] = "ok" if cursor.fetchone()[0] else "unavailable"
        else:
            checks["search"] = "unavailable"
    except Exception:
        checks["search"] = "unavailable"

    try:
        cache.set("marketlift:readiness", "ok", timeout=10)
        checks["redis"] = (
            "ok" if cache.get("marketlift:readiness") == "ok" else "unavailable"
        )
    except Exception:
        checks["redis"] = "unavailable"

    try:
        layer = get_channel_layer()
        if layer is None:
            raise RuntimeError("No channel layer configured")
        channel_name = async_to_sync(layer.new_channel)("marketlift.readiness.")
        async_to_sync(layer.send)(channel_name, {"type": "readiness.ping"})
        event = async_to_sync(layer.receive)(channel_name)
        checks["realtime"] = (
            "ok" if event.get("type") == "readiness.ping" else "unavailable"
        )
    except Exception:
        checks["realtime"] = "unavailable"

    ready = all(value == "ok" for value in checks.values())
    return Response(
        {"status": "ok" if ready else "unavailable", "checks": checks},
        status=200 if ready else HTTP_503_SERVICE_UNAVAILABLE,
    )
