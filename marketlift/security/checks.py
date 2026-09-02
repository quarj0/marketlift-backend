from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

from marketlift.markets.service import enabled_market_profiles


@register(Tags.files)
def marketlift_storage_checks(app_configs, **kwargs):
    """Catch incomplete object-storage configuration in every environment."""
    issues = []
    r2_any = getattr(settings, "MARKETLIFT_R2_ANY_CONFIGURED", False)
    r2_ready = getattr(settings, "MARKETLIFT_R2_CONFIGURED", False)
    if r2_any and not r2_ready:
        issues.append(
            Error(
                "R2/S3-compatible object storage is only partially configured.",
                hint=(
                    "Set the access key, secret, endpoint and all four logical "
                    "bucket names, or remove the partial R2 configuration."
                ),
                id="marketlift.E014",
            )
        )
    if r2_ready:
        buckets = getattr(settings, "MARKETLIFT_STORAGE_BUCKETS", {})
        configured_names = [
            buckets.get(alias, "")
            for alias in ("public", "private", "evidence", "temp")
        ]
        if len(set(configured_names)) != 4:
            issues.append(
                Error(
                    "Public, private, evidence and temporary uploads must use distinct buckets.",
                    id="marketlift.E015",
                )
            )
    return issues


@register(Tags.security, deploy=True)
def marketlift_deploy_checks(app_configs, **kwargs):
    if not getattr(settings, "IS_PRODUCTION", False):
        return []

    issues = []
    secret = getattr(settings, "SECRET_KEY", "")
    if not secret or secret.startswith("django-insecure-") or len(secret) < 40:
        issues.append(
            Error(
                "Production DJANGO_SECRET_KEY is missing or insecure.",
                id="marketlift.E001",
            )
        )
    if settings.DEBUG:
        issues.append(
            Error("DJANGO_DEBUG must be false in production.", id="marketlift.E002")
        )

    hosts = set(getattr(settings, "ALLOWED_HOSTS", []))
    if not hosts or "*" in hosts or hosts <= {"localhost", "127.0.0.1", "[::1]"}:
        issues.append(
            Error(
                "Set explicit production DJANGO_ALLOWED_HOSTS; wildcard/localhost-only hosts are not accepted.",
                id="marketlift.E003",
            )
        )
    if not settings.SESSION_COOKIE_SECURE or not settings.CSRF_COOKIE_SECURE:
        issues.append(
            Error(
                "Secure session and CSRF cookies are required in production.",
                id="marketlift.E004",
            )
        )
    if not settings.SECURE_SSL_REDIRECT:
        issues.append(
            Error(
                "SECURE_SSL_REDIRECT must be enabled for production login/session traffic.",
                id="marketlift.E005",
            )
        )
    payments_enabled = getattr(settings, "MARKETLIFT_PAYMENTS_ENABLED", False)
    provider = (
        str(getattr(settings, "MARKETLIFT_PAYMENT_PROVIDER", "auto")).strip().lower()
    )
    if provider in {"auto", "market", "market_default"}:
        providers = {
            profile.default_payment_provider for profile in enabled_market_profiles()
        }
    else:
        providers = {provider}
    if payments_enabled and (
        "mock" in providers or getattr(settings, "PAYMENT_MOCK_AUTO_APPROVE", False)
    ):
        issues.append(
            Error(
                "Mock/auto-approved payments must not be enabled in production.",
                id="marketlift.E006",
            )
        )
    if (
        payments_enabled
        and "mercado_pago" in providers
        and (
            not getattr(settings, "MERCADO_PAGO_ACCESS_TOKEN", "")
            or not getattr(settings, "MERCADO_PAGO_WEBHOOK_SECRET", "")
        )
    ):
        issues.append(
            Error(
                "Mercado Pago production credentials/webhook secret are incomplete.",
                id="marketlift.E007",
            )
        )
    if (
        payments_enabled
        and "paystack" in providers
        and not getattr(settings, "PAYSTACK_SECRET_KEY", "")
    ):
        issues.append(
            Error(
                "Paystack production secret key is missing.",
                id="marketlift.E020",
            )
        )
    if getattr(settings, "MARKETLIFT_IDENTITY_VERIFICATION_ENABLED", False):
        try:
            from platform_settings.models import Market

            identity_providers = set(
                Market.objects.filter(is_enabled=True).values_list(
                    "identity_provider", flat=True
                )
            )
        except Exception:
            identity_providers = {
                getattr(
                    settings, "MARKETLIFT_IDENTITY_VERIFICATION_PROVIDER", "disabled"
                )
            }
        if not identity_providers or any(
            (provider or "").strip().lower() in {"", "disabled", "internal"}
            for provider in identity_providers
        ):
            issues.append(
                Error(
                    "Every enabled market requires a certified external identity provider when identity verification is enabled.",
                    id="marketlift.E019",
                )
            )
    if not str(getattr(settings, "MARKETLIFT_FRONTEND_URL", "")).startswith("https://"):
        issues.append(
            Error(
                "MARKETLIFT_FRONTEND_URL must use HTTPS in production.",
                id="marketlift.E008",
            )
        )
    origins = list(getattr(settings, "CORS_ALLOWED_ORIGINS", [])) + list(
        getattr(settings, "CSRF_TRUSTED_ORIGINS", [])
    )
    if any(not x.startswith("https://") for x in origins):
        issues.append(
            Error("Production CORS/CSRF origins must use HTTPS.", id="marketlift.E009")
        )
    email_backend = getattr(settings, "EMAIL_BACKEND", "")
    if "console.EmailBackend" in email_backend:
        issues.append(
            Error(
                "Configure a real EMAIL_BACKEND before production account verification/password reset.",
                id="marketlift.E010",
            )
        )
    if "smtp.EmailBackend" in email_backend:
        missing_email_settings = [
            name
            for name in ("EMAIL_HOST", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD")
            if not getattr(settings, name, "")
        ]
        if missing_email_settings:
            issues.append(
                Error(
                    "SMTP email delivery is missing required credentials.",
                    hint=f"Set {', '.join(missing_email_settings)}.",
                    id="marketlift.E017",
                )
            )
        if getattr(settings, "EMAIL_USE_TLS", False) == getattr(
            settings, "EMAIL_USE_SSL", False
        ):
            issues.append(
                Error(
                    "SMTP must enable exactly one transport-security mode.",
                    hint="Use EMAIL_USE_TLS=true for port 587 or EMAIL_USE_SSL=true for port 465.",
                    id="marketlift.E018",
                )
            )
    if email_backend == "anymail.backends.resend.EmailBackend":
        anymail = getattr(settings, "ANYMAIL", {}) or {}
        if not anymail.get("RESEND_API_KEY"):
            issues.append(
                Error(
                    "Resend email delivery is missing RESEND_API_KEY.",
                    hint="Set RESEND_API_KEY on the production service.",
                    id="marketlift.E021",
                )
            )
    channel_layer = getattr(settings, "CHANNEL_LAYERS", {}).get("default", {})
    channel_backend = channel_layer.get("BACKEND", "")
    if not channel_backend or channel_backend == "channels.layers.InMemoryChannelLayer":
        issues.append(
            Error(
                "Production realtime delivery requires a shared channel layer; configure a Redis-compatible CHANNEL_REDIS_URL.",
                id="marketlift.E011",
            )
        )
    websocket_origins = list(
        getattr(settings, "MARKETLIFT_WEBSOCKET_ALLOWED_ORIGINS", [])
    )
    if not websocket_origins or any(
        not origin.startswith("https://") for origin in websocket_origins
    ):
        issues.append(
            Error(
                "Production WebSocket origins must be explicit HTTPS origins.",
                id="marketlift.E012",
            )
        )
    r2_ready = getattr(settings, "MARKETLIFT_R2_CONFIGURED", False)
    if r2_ready:
        endpoint = str(getattr(settings, "MARKETLIFT_S3_ENDPOINT_URL", ""))
        if not endpoint.startswith("https://"):
            issues.append(
                Error(
                    "Production S3-compatible object storage must use an HTTPS endpoint.",
                    id="marketlift.E016",
                )
            )
    else:
        storage = getattr(settings, "MARKETLIFT_STORAGE_BACKENDS", {}).get(
            "default", ""
        )
        if storage.endswith("LocalStorageBackend"):
            issues.append(
                Warning(
                    "Local upload storage is configured. Ensure the production filesystem is durable or select a remote adapter.",
                    id="marketlift.W002",
                )
            )
    if settings.DATABASES["default"].get("ENGINE") in {
        "django.db.backends.postgresql",
        "django.contrib.gis.db.backends.postgis",
    } and not getattr(settings, "DB_SSLMODE", ""):
        issues.append(
            Warning(
                "DB_SSLMODE is empty. Confirm transport encryption requirements with the selected PostgreSQL host.",
                id="marketlift.W003",
            )
        )
    if any("localhost" in x or "127.0.0.1" in x for x in origins):
        issues.append(
            Warning(
                "Development localhost origins are still present in production CORS/CSRF configuration.",
                id="marketlift.W004",
            )
        )
    if getattr(settings, "SECURE_HSTS_SECONDS", 0) <= 0:
        issues.append(
            Warning(
                "HSTS is disabled. Enable it after HTTPS is confirmed end-to-end.",
                id="marketlift.W005",
            )
        )
    if not getattr(settings, "MARKETLIFT_DISABLE_GRAPHQL_INTROSPECTION", False):
        issues.append(
            Warning(
                "GraphQL introspection is enabled in production.", id="marketlift.W006"
            )
        )
    if (
        settings.DATABASES["default"].get("ENGINE")
        != "django.contrib.gis.db.backends.postgis"
    ):
        issues.append(
            Error(
                "Geospatial listing search requires the GeoDjango PostGIS database backend.",
                id="marketlift.E013",
            )
        )
    if not getattr(settings, "MARKETLIFT_REQUIRE_RESOLVED_LISTING_LOCATION", False):
        issues.append(
            Warning(
                "Resolved listing locations are not required in production; enable MARKETLIFT_REQUIRE_RESOLVED_LISTING_LOCATION for canonical geocoded locations.",
                id="marketlift.W007",
            )
        )
    if getattr(settings, "MARKETLIFT_GEOCODER_BACKEND", "").endswith(
        "DisabledGeocoder"
    ):
        issues.append(
            Warning(
                "No location geocoder is configured. Radius search still works with coordinates, but place lookup/reverse-geocoding is disabled.",
                id="marketlift.W008",
            )
        )
    if (
        getattr(settings, "MARKETLIFT_GEOCODER_BACKEND", "").endswith(
            "NominatimGeocoder"
        )
        and getattr(settings, "MARKETLIFT_NOMINATIM_BASE_URL", "")
        == "https://nominatim.openstreetmap.org"
    ):
        issues.append(
            Warning(
                "The public Nominatim endpoint is configured in production. Select a geocoding service/self-hosted endpoint appropriate for production traffic and SLA requirements.",
                id="marketlift.W009",
            )
        )
    return issues
