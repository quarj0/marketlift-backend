import asyncio
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.cache import cache
from django.db import connection
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import HTTP_503_SERVICE_UNAVAILABLE
from django.conf import settings
from marketlift.markets.pricing import market_pricing_readiness
from marketlift.markets.service import (
    active_market_profile,
    enabled_market_profiles,
    identity_provider_for_country_code,
)
from platform_settings.models import Market, PlatformConfiguration
from platform_settings.readiness import (
    identity_provider_readiness,
    payment_provider_readiness,
)

logger = logging.getLogger(__name__)


async def _realtime_round_trip(layer):
    async with asyncio.timeout(settings.MARKETLIFT_DEPENDENCY_TIMEOUT_SECONDS):
        channel_name = await layer.new_channel("marketlift.readiness.")
        await layer.send(channel_name, {"type": "readiness.ping"})
        return await layer.receive(channel_name)


@api_view(["GET"])
@permission_classes([AllowAny])
def market_profile(request):
    """Public deployment capabilities used to configure marketplace frontends."""

    active = active_market_profile()
    enabled = enabled_market_profiles()
    rows = {
        row.code: row
        for row in Market.objects.filter(code__in=[profile.code for profile in enabled])
    }

    def public_profile(profile):
        payload = profile.as_public_dict()
        row = rows.get(profile.code)
        payment_ready = False
        identity_ready = False
        if row is not None:
            provider_ready, _ = payment_provider_readiness(row)
            pricing_ready, _ = market_pricing_readiness(row)
            identity_provider_ready, _ = identity_provider_readiness(row)
            payment_ready = bool(
                settings.MARKETLIFT_PAYMENTS_ENABLED
                and provider_ready
                and pricing_ready
                and row.payment_methods
            )
            identity_ready = bool(
                getattr(settings, "MARKETLIFT_IDENTITY_VERIFICATION_ENABLED", False)
                and identity_provider_ready
            )
        payload["paymentsEnabled"] = payment_ready
        payload["identityVerificationEnabled"] = identity_ready
        return payload

    enabled_payloads = [public_profile(profile) for profile in enabled]
    active_payload = next(
        (
            payload
            for payload in enabled_payloads
            if payload["countryCode"] == active.country_code
        ),
        public_profile(active),
    )
    return Response(
        {
            "active": active_payload,
            "enabledMarkets": enabled_payloads,
            "payments": {
                "enabled": bool(active_payload["paymentsEnabled"]),
                "provider": active.default_payment_provider,
                "methods": list(active.payment_methods),
            },
            "identityVerification": {
                "enabled": bool(active_payload["identityVerificationEnabled"]),
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
def maintenance_status(request):
    """Minimal public status used by the marketplace maintenance guard.

    This endpoint intentionally exposes only the maintenance boolean. It does
    not reveal administrator identity, reasons, internal notes, or deployment
    metadata.
    """

    maintenance = None
    try:
        maintenance = cache.get("ml:platform:maintenance")
    except Exception:
        pass
    if maintenance is None:
        try:
            maintenance = PlatformConfiguration.load().maintenance_mode
            try:
                cache.set("ml:platform:maintenance", bool(maintenance), timeout=30)
            except Exception:
                pass
        except Exception:
            # If configuration storage is unavailable, readiness will separately
            # report the outage. Do not accidentally lock users out indefinitely.
            maintenance = False
    response = Response({"maintenance": bool(maintenance)})
    response["Cache-Control"] = "no-store, max-age=0"
    return response


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
        event = async_to_sync(_realtime_round_trip)(layer)
        checks["realtime"] = (
            "ok" if event.get("type") == "readiness.ping" else "unavailable"
        )
    except Exception as exc:
        logger.error("readiness check=realtime error_type=%s", type(exc).__name__)
        checks["realtime"] = "unavailable"

    if settings.MARKETLIFT_REQUIRE_WORKER_HEARTBEAT:
        try:
            checks["worker"] = (
                "ok" if cache.get("marketlift:worker-heartbeat") else "unavailable"
            )
        except Exception:
            checks["worker"] = "unavailable"

    ready = all(value == "ok" for value in checks.values())
    return Response(
        {"status": "ok" if ready else "unavailable", "checks": checks},
        status=200 if ready else HTTP_503_SERVICE_UNAVAILABLE,
    )
