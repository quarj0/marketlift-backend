from django.conf import settings
from django.core.checks import Error, Tags, Warning, register


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
    provider = getattr(settings, "MARKETLIFT_PAYMENT_PROVIDER", "mock")
    if provider == "mock" or getattr(settings, "PAYMENT_MOCK_AUTO_APPROVE", False):
        issues.append(
            Error(
                "Mock/auto-approved payments must not be enabled in production.",
                id="marketlift.E006",
            )
        )
    if provider == "mercado_pago" and (
        not getattr(settings, "MERCADO_PAGO_ACCESS_TOKEN", "")
        or not getattr(settings, "MERCADO_PAGO_WEBHOOK_SECRET", "")
    ):
        issues.append(
            Error(
                "Mercado Pago production credentials/webhook secret are incomplete.",
                id="marketlift.E007",
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
    if "console.EmailBackend" in getattr(settings, "EMAIL_BACKEND", ""):
        issues.append(
            Error(
                "Configure a real EMAIL_BACKEND before production account verification/password reset.",
                id="marketlift.E010",
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
    storage = getattr(settings, "MARKETLIFT_STORAGE_BACKENDS", {}).get("default", "")
    if storage.endswith("LocalStorageBackend"):
        issues.append(
            Warning(
                "Local upload storage is configured. Ensure the production filesystem is durable or select a remote adapter.",
                id="marketlift.W002",
            )
        )
    if settings.DATABASES["default"].get(
        "ENGINE"
    ) == "django.db.backends.postgresql" and not getattr(settings, "DB_SSLMODE", ""):
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
    return issues
