from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.conf import settings
from django.core.cache import cache
from django.db import connection

from marketlift.markets.pricing import market_pricing_readiness
from platform_settings.models import Market, PlatformConfiguration


@dataclass(frozen=True)
class ReadinessItem:
    key: str
    label: str
    category: str
    status: str
    required: bool
    message: str
    hint: str = ""


@dataclass(frozen=True)
class MarketReadiness:
    payment_ready: bool
    payment_message: str
    identity_ready: bool
    identity_message: str
    launch_ready: bool
    launch_issues: list[str]


def _item(
    key: str,
    label: str,
    category: str,
    ok: bool,
    *,
    required: bool,
    message: str,
    hint: str = "",
    warning: bool = False,
) -> ReadinessItem:
    if ok:
        status = "ready"
    elif warning or not required:
        status = "warning"
    else:
        status = "blocked"
    return ReadinessItem(key, label, category, status, required, message, hint)


def payment_provider_readiness(market: Market) -> tuple[bool, str]:
    provider = (market.payment_provider or "disabled").strip().lower()
    if provider == "disabled":
        return False, "Payment provider is disabled."
    if provider == "mock":
        return False, "Mock payments are test-only and cannot be used for production."
    if provider == "paystack":
        if not getattr(settings, "PAYSTACK_SECRET_KEY", ""):
            return False, "Paystack secret key is not configured."
        if not getattr(settings, "PAYSTACK_CALLBACK_URL", ""):
            return False, "Paystack callback URL is not configured."
        return True, "Paystack credentials and callback URL are configured."
    if provider == "mercado_pago":
        missing = []
        if not getattr(settings, "MERCADO_PAGO_ACCESS_TOKEN", ""):
            missing.append("access token")
        if not getattr(settings, "MERCADO_PAGO_WEBHOOK_SECRET", ""):
            missing.append("webhook secret")
        if missing:
            return False, f"Mercado Pago is missing {', '.join(missing)}."
        if "card" in (market.payment_methods or []):
            return (
                False,
                "Mercado Pago card checkout requires client-side tokenization; disable card until the Mercado Pago SDK adapter is configured.",
            )
        return (
            True,
            "Mercado Pago credentials are configured for the enabled payment methods.",
        )
    return False, f"Unsupported payment provider: {provider}."


def identity_provider_readiness(market: Market) -> tuple[bool, str]:
    if not getattr(settings, "MARKETLIFT_IDENTITY_VERIFICATION_ENABLED", False):
        return False, "Identity verification is globally disabled."
    provider = (market.identity_provider or "disabled").strip().lower()
    if provider in {"", "disabled", "internal"}:
        return False, "A certified external identity provider is not configured."
    if not getattr(settings, "MARKETLIFT_IDENTITY_PROVIDER_READY", False):
        return (
            False,
            f"Identity provider '{provider}' is selected, but its production adapter has not been marked ready.",
        )
    # Provider-specific adapters can add deeper health checks here. Keeping the
    # contract generic means a future Ghana/Nigeria/Kenya adapter does not leak
    # credentials or vendor-specific fields into the admin UI.
    return True, f"Identity provider '{provider}' is configured and marked ready."


def market_readiness(market: Market) -> MarketReadiness:
    pricing_ready, pricing_issues = market_pricing_readiness(market)
    payment_ready, payment_message = payment_provider_readiness(market)
    identity_ready, identity_message = identity_provider_readiness(market)
    config = PlatformConfiguration.load()

    issues: list[str] = []
    if not market.payment_methods and market.payment_provider != "disabled":
        issues.append("No payment methods are enabled.")
    if getattr(settings, "MARKETLIFT_PAYMENTS_ENABLED", False):
        if market.payment_provider == "disabled":
            issues.append(
                "Payments are globally enabled but this market has no payment provider."
            )
        elif not payment_ready:
            issues.append(payment_message)
        if market.payment_provider != "disabled" and not pricing_ready:
            issues.extend(pricing_issues)
    if config.seller_verification_required:
        if not identity_ready:
            issues.append(identity_message)

    return MarketReadiness(
        payment_ready=payment_ready,
        payment_message=payment_message,
        identity_ready=identity_ready,
        identity_message=identity_message,
        launch_ready=not issues,
        launch_issues=issues,
    )


def _database_check() -> tuple[bool, str]:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        engine = connection.settings_dict.get("ENGINE", "")
        return engine == "django.contrib.gis.db.backends.postgis", (
            "Database is reachable with the PostGIS backend."
            if engine.endswith("postgis")
            else "Database is reachable but GeoDjango PostGIS is not configured."
        )
    except Exception:
        return False, "Database connection is unavailable."


def _redis_check() -> tuple[bool, str]:
    try:
        cache.set("marketlift:admin-readiness", "ok", timeout=10)
        if cache.get("marketlift:admin-readiness") == "ok":
            return True, "Shared cache/Redis is reachable."
    except Exception:
        pass
    return False, "Shared cache/Redis is unavailable."


def deployment_readiness_items() -> list[ReadinessItem]:
    config = PlatformConfiguration.load()
    items: list[ReadinessItem] = []

    production_mode = bool(getattr(settings, "IS_PRODUCTION", False))
    items.append(
        _item(
            "environment",
            "Production environment mode",
            "Deployment",
            production_mode,
            required=False,
            warning=True,
            message=(
                "Application is running in production mode."
                if production_mode
                else "Application is not running in production mode."
            ),
            hint="Set MARKETLIFT_ENV=production on the production deployment.",
        )
    )

    secret = getattr(settings, "SECRET_KEY", "")
    items.append(
        _item(
            "secret_key",
            "Django secret key",
            "Security",
            bool(secret)
            and len(secret) >= 40
            and not secret.startswith("django-insecure-"),
            required=True,
            message=(
                "Application signing key is production-safe."
                if secret
                and len(secret) >= 40
                and not secret.startswith("django-insecure-")
                else "Django secret key is missing or insecure."
            ),
            hint="Set DJANGO_SECRET_KEY to a strong secret.",
        )
    )
    items.append(
        _item(
            "debug",
            "Debug mode",
            "Security",
            not settings.DEBUG,
            required=True,
            message=(
                "Debug mode is disabled."
                if not settings.DEBUG
                else "Debug mode is enabled."
            ),
            hint="Set DJANGO_DEBUG=false in production.",
        )
    )
    hosts = set(getattr(settings, "ALLOWED_HOSTS", []))
    hosts_ok = (
        bool(hosts)
        and "*" not in hosts
        and not hosts <= {"localhost", "127.0.0.1", "[::1]"}
    )
    items.append(
        _item(
            "allowed_hosts",
            "Allowed hosts",
            "Security",
            hosts_ok,
            required=True,
            message=(
                "Explicit production hosts are configured."
                if hosts_ok
                else "Allowed hosts are wildcard, empty or localhost-only."
            ),
            hint="Set DJANGO_ALLOWED_HOSTS to the API hostnames.",
        )
    )
    cookie_ok = bool(
        settings.SESSION_COOKIE_SECURE
        and settings.CSRF_COOKIE_SECURE
        and settings.SECURE_SSL_REDIRECT
    )
    items.append(
        _item(
            "https_cookies",
            "HTTPS and secure cookies",
            "Security",
            cookie_ok,
            required=True,
            message=(
                "HTTPS redirect and secure session/CSRF cookies are enabled."
                if cookie_ok
                else "HTTPS redirect or secure cookies are not fully enabled."
            ),
            hint="Enable SECURE_SSL_REDIRECT, SESSION_COOKIE_SECURE and CSRF_COOKIE_SECURE.",
        )
    )

    db_ok, db_message = _database_check()
    items.append(
        _item(
            "database",
            "PostgreSQL/PostGIS",
            "Database",
            db_ok,
            required=True,
            message=db_message,
            hint="Use django.contrib.gis.db.backends.postgis and ensure the database is reachable.",
        )
    )
    sslmode = str(getattr(settings, "DB_SSLMODE", "")).strip()
    items.append(
        _item(
            "database_tls",
            "Database TLS",
            "Database",
            bool(sslmode),
            required=False,
            warning=not bool(sslmode),
            message=(
                f"Database sslmode is {sslmode}."
                if sslmode
                else "Database sslmode is not explicitly configured."
            ),
            hint="Set DB_SSLMODE according to your PostgreSQL provider's TLS requirement.",
        )
    )

    redis_ok, redis_message = _redis_check()
    items.append(
        _item(
            "redis",
            "Redis/cache",
            "Realtime",
            redis_ok,
            required=True,
            message=redis_message,
            hint="Configure REDIS_URL / CHANNEL_REDIS_URL to a shared Redis-compatible service.",
        )
    )
    channel_backend = (
        getattr(settings, "CHANNEL_LAYERS", {}).get("default", {}).get("BACKEND", "")
    )
    shared_channel = (
        bool(channel_backend)
        and channel_backend != "channels.layers.InMemoryChannelLayer"
    )
    items.append(
        _item(
            "channel_layer",
            "WebSocket channel layer",
            "Realtime",
            shared_channel,
            required=True,
            message=(
                "A shared channel layer is configured."
                if shared_channel
                else "Realtime is using no channel layer or an in-memory layer."
            ),
            hint="Configure the Redis-backed Channels layer for production.",
        )
    )

    email_backend = str(getattr(settings, "EMAIL_BACKEND", ""))
    email_ready = "console.EmailBackend" not in email_backend and bool(email_backend)
    if "smtp.EmailBackend" in email_backend:
        email_ready = email_ready and all(
            getattr(settings, name, "")
            for name in ("EMAIL_HOST", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD")
        )
    items.append(
        _item(
            "email",
            "Transactional email",
            "Email",
            email_ready,
            required=True,
            message=(
                "Transactional email is configured."
                if email_ready
                else "A production email backend/credentials are not configured."
            ),
            hint="Configure SMTP or another production email backend for verification and password reset.",
        )
    )
    support_email = str(config.support_email or "").strip().lower()
    support_ok = (
        bool(support_email)
        and not support_email.endswith(".local")
        and "@" in support_email
    )
    items.append(
        _item(
            "support_email",
            "Support email",
            "Email",
            support_ok,
            required=False,
            warning=True,
            message=(
                f"Support email is {config.support_email}."
                if support_ok
                else "Support email still uses a local/placeholder address."
            ),
            hint="Set a monitored public support address in Admin → Settings.",
        )
    )

    storage_ready = bool(getattr(settings, "MARKETLIFT_R2_CONFIGURED", False))
    storage_backend = str(
        getattr(settings, "MARKETLIFT_STORAGE_BACKENDS", {}).get("default", "")
    )
    items.append(
        _item(
            "storage",
            "Object storage",
            "Storage",
            storage_ready,
            required=False,
            warning=not storage_ready,
            message=(
                "S3-compatible object storage is configured."
                if storage_ready
                else f"Remote object storage is not fully configured ({storage_backend or 'local/default'})."
            ),
            hint="Configure the S3-compatible/R2 credentials and four logical buckets before durable production uploads.",
        )
    )

    frontend_url = str(getattr(settings, "MARKETLIFT_FRONTEND_URL", ""))
    admin_url = str(getattr(settings, "MARKETLIFT_ADMIN_FRONTEND_URL", ""))
    origins = list(getattr(settings, "CORS_ALLOWED_ORIGINS", [])) + list(
        getattr(settings, "CSRF_TRUSTED_ORIGINS", [])
    )
    origin_ok = (
        frontend_url.startswith("https://")
        and admin_url.startswith("https://")
        and bool(origins)
        and all(origin.startswith("https://") for origin in origins)
    )
    items.append(
        _item(
            "origins",
            "Frontend URLs and trusted origins",
            "Security",
            origin_ok,
            required=True,
            message=(
                "Frontend/admin URLs and trusted origins use HTTPS."
                if origin_ok
                else "Frontend/admin URLs or CORS/CSRF origins are not production HTTPS values."
            ),
            hint="Set MARKETLIFT_FRONTEND_URL, MARKETLIFT_ADMIN_FRONTEND_URL, CORS_ALLOWED_ORIGINS and CSRF_TRUSTED_ORIGINS.",
        )
    )
    email_backend = str(getattr(settings, "EMAIL_BACKEND", ""))
    anymail = getattr(settings, "ANYMAIL", {}) or {}
    admin_email_login_ready = bool(getattr(settings, "DEFAULT_FROM_EMAIL", "")) and (
        not getattr(settings, "IS_PRODUCTION", False)
        or (
            email_backend == "anymail.backends.resend.EmailBackend"
            and bool(anymail.get("RESEND_API_KEY"))
        )
    )
    items.append(
        _item(
            "admin_email_login",
            "Administrator email sign-in",
            "Security",
            admin_email_login_ready,
            required=True,
            message=(
                "Passwordless administrator sign-in email delivery is configured."
                if admin_email_login_ready
                else "Administrator sign-in email delivery is not configured."
            ),
            hint="Configure RESEND_API_KEY and DEFAULT_FROM_EMAIL for passwordless admin sign-in.",
        )
    )

    geocoder = str(getattr(settings, "MARKETLIFT_GEOCODER_BACKEND", ""))
    geocoder_ready = bool(geocoder) and not geocoder.endswith("DisabledGeocoder")
    public_nominatim = (
        geocoder.endswith("NominatimGeocoder")
        and getattr(settings, "MARKETLIFT_NOMINATIM_BASE_URL", "")
        == "https://nominatim.openstreetmap.org"
    )
    items.append(
        _item(
            "geocoder",
            "Location geocoder",
            "Location",
            geocoder_ready and not public_nominatim,
            required=False,
            warning=True,
            message=(
                "Production geocoder is configured."
                if geocoder_ready and not public_nominatim
                else (
                    "Public Nominatim is configured; suitable for development/light use, not a production SLA."
                    if public_nominatim
                    else "No geocoder is configured."
                )
            ),
            hint="Configure a production geocoding provider or self-hosted endpoint.",
        )
    )

    payments_enabled = bool(getattr(settings, "MARKETLIFT_PAYMENTS_ENABLED", False))
    enabled_markets = list(Market.objects.filter(is_enabled=True))
    payment_failures: list[str] = []
    if payments_enabled:
        for market in enabled_markets:
            ready = market_readiness(market)
            if market.payment_provider != "disabled" and not ready.payment_ready:
                payment_failures.append(f"{market.code}: {ready.payment_message}")
            if market.payment_provider != "disabled":
                pricing_ready, pricing_issues = market_pricing_readiness(market)
                if not pricing_ready:
                    payment_failures.extend(
                        f"{market.code}: {issue}" for issue in pricing_issues
                    )
    items.append(
        _item(
            "payments",
            "Seller-service payments",
            "Payments",
            payments_enabled and not payment_failures,
            required=False,
            warning=True,
            message=(
                "Payments are enabled and configured for enabled markets."
                if payments_enabled and not payment_failures
                else (
                    "Payments are globally disabled."
                    if not payments_enabled
                    else "Payment configuration is incomplete: "
                    + "; ".join(payment_failures)
                )
            ),
            hint="Enable MARKETLIFT_PAYMENTS_ENABLED only after provider credentials, webhooks and per-market prices are configured.",
        )
    )

    identity_enabled = bool(
        getattr(settings, "MARKETLIFT_IDENTITY_VERIFICATION_ENABLED", False)
    )
    identity_failures = [
        f"{m.code}: {identity_provider_readiness(m)[1]}"
        for m in enabled_markets
        if identity_enabled and not identity_provider_readiness(m)[0]
    ]
    identity_required = bool(config.seller_verification_required)
    items.append(
        _item(
            "identity",
            "Seller identity verification",
            "Verification",
            identity_enabled and not identity_failures,
            required=identity_required,
            warning=not identity_required,
            message=(
                "Identity verification is enabled for all enabled markets."
                if identity_enabled and not identity_failures
                else (
                    "Identity verification is globally disabled."
                    if not identity_enabled
                    else "Identity provider configuration is incomplete: "
                    + "; ".join(identity_failures)
                )
            ),
            hint="Configure a certified identity provider per enabled market before requiring seller verification.",
        )
    )

    default_count = Market.objects.filter(is_enabled=True, is_default=True).count()
    items.append(
        _item(
            "default_market",
            "Default enabled market",
            "Markets",
            default_count == 1,
            required=True,
            message=(
                "Exactly one enabled default market is configured."
                if default_count == 1
                else f"Expected one enabled default market; found {default_count}."
            ),
            hint="Use Admin → Markets to select one default market.",
        )
    )

    if getattr(settings, "IS_PRODUCTION", False):
        items.append(
            _item(
                "graphql_introspection",
                "GraphQL introspection",
                "Security",
                bool(
                    getattr(settings, "MARKETLIFT_DISABLE_GRAPHQL_INTROSPECTION", False)
                ),
                required=False,
                warning=True,
                message=(
                    "GraphQL introspection is disabled."
                    if getattr(
                        settings, "MARKETLIFT_DISABLE_GRAPHQL_INTROSPECTION", False
                    )
                    else "GraphQL introspection is enabled."
                ),
                hint="Disable introspection in production unless operationally required.",
            )
        )
        items.append(
            _item(
                "hsts",
                "HSTS",
                "Security",
                getattr(settings, "SECURE_HSTS_SECONDS", 0) > 0,
                required=False,
                warning=True,
                message=(
                    "HSTS is enabled."
                    if getattr(settings, "SECURE_HSTS_SECONDS", 0) > 0
                    else "HSTS is disabled."
                ),
                hint="Enable HSTS after HTTPS is confirmed end-to-end.",
            )
        )

    return items


def readiness_summary(items: Iterable[ReadinessItem]) -> tuple[bool, int, int]:
    rows = list(items)
    blockers = sum(1 for row in rows if row.status == "blocked")
    warnings = sum(1 for row in rows if row.status == "warning")
    return blockers == 0, blockers, warnings
