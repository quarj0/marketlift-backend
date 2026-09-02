"""Django settings for Marketlift."""

import json
import os
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

from dotenv import load_dotenv

from marketlift.markets.profiles import get_market_profile, market_profiles_for_codes

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [
        item.strip() for item in os.getenv(name, default).split(",") if item.strip()
    ]


def env_text(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


MARKETLIFT_ENV = os.getenv("MARKETLIFT_ENV", "development").strip().lower()
IS_PRODUCTION = MARKETLIFT_ENV in {"production", "prod"}

# Market/country configuration. Domain code uses ISO country/currency values and
# provider interfaces; Brazil is only the compatibility default. A deployment can
# switch markets without rewriting listing/search/payment business logic.
MARKETLIFT_MARKET_CODE = os.getenv("MARKETLIFT_MARKET_CODE", "BR").strip().upper()
MARKETLIFT_MARKET = get_market_profile(MARKETLIFT_MARKET_CODE)
MARKETLIFT_ENABLED_MARKET_CODES = env_list(
    "MARKETLIFT_ENABLED_MARKETS", MARKETLIFT_MARKET_CODE
)
if MARKETLIFT_MARKET_CODE not in {
    code.upper() for code in MARKETLIFT_ENABLED_MARKET_CODES
}:
    MARKETLIFT_ENABLED_MARKET_CODES.insert(0, MARKETLIFT_MARKET_CODE)
MARKETLIFT_ENABLED_MARKETS = market_profiles_for_codes(
    [code.upper() for code in MARKETLIFT_ENABLED_MARKET_CODES]
)
MARKETLIFT_SUPPORTED_COUNTRY_CODES = tuple(
    profile.country_code for profile in MARKETLIFT_ENABLED_MARKETS
)
MARKETLIFT_MARKET_COUNTRY_CODE = MARKETLIFT_MARKET.country_code
MARKETLIFT_MARKET_LOCALE = MARKETLIFT_MARKET.locale
MARKETLIFT_MARKET_CURRENCY = MARKETLIFT_MARKET.currency
MARKETLIFT_MARKET_CURRENCY_SYMBOL = MARKETLIFT_MARKET.currency_symbol
MARKETLIFT_MARKET_PAYMENT_METHODS = MARKETLIFT_MARKET.payment_methods

SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY", "django-insecure-marketlift-local-development-only"
)
SECRET_KEY_FALLBACKS = env_list("DJANGO_SECRET_KEY_FALLBACKS")
DEBUG = env_bool("DJANGO_DEBUG", not IS_PRODUCTION)
ALLOWED_HOSTS = env_list(
    "DJANGO_ALLOWED_HOSTS",
    "marketlift.com.br,api.marketlift.com.br,dash.marketlift.com.br",
)

INSTALLED_APPS = [
    "daphne",
    "channels",
    "marketlift.realtime",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "corsheaders",
    "rest_framework",
    "strawberry_django",
    "accounts",
    "sellers",
    "listings",
    "categories",
    "subscriptions",
    "promotions",
    "payments",
    "verifications",
    "uploads",
    "messaging",
    "moderation",
    "reports",
    "notifications",
    "audit",
    "reviews",
    "saved_searches",
    "support",
    "platform_settings",
    "marketlift.security",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "marketlift.security.middleware.ClientScopedSessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "marketlift.security.middleware.SecurityRateLimitMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "marketlift.security.middleware.MaintenanceModeMiddleware",
]

ROOT_URLCONF = "marketlift.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "marketlift.wsgi.application"
ASGI_APPLICATION = "marketlift.asgi.application"

DATABASE_URL = env_text("DATABASE_URL")


def database_config() -> dict:
    """Build the runtime database config from one provider-neutral URL.

    Production uses Neon via DATABASE_URL. Local development intentionally has
    a zero-config PostGIS fallback matching docker-compose.
    """
    if not DATABASE_URL:
        return {
            "ENGINE": "django.contrib.gis.db.backends.postgis",
            "NAME": "marketlift",
            "USER": "marketlift",
            "PASSWORD": "marketlift",
            "HOST": "127.0.0.1",
            "PORT": "5433",
            "CONN_MAX_AGE": 60,
            "CONN_HEALTH_CHECKS": True,
        }

    parsed = urlsplit(DATABASE_URL)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise RuntimeError("DATABASE_URL must be a PostgreSQL URL.")

    options = dict(parse_qsl(parsed.query, keep_blank_values=False))
    if IS_PRODUCTION:
        options.setdefault("sslmode", "require")

    config = {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": parsed.path.lstrip("/"),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or 5432),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }
    if options:
        config["OPTIONS"] = options
    return config


DATABASES = {"default": database_config()}
DB_SSLMODE = DATABASES["default"].get("OPTIONS", {}).get("sslmode", "")


AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = env_text("DJANGO_LANGUAGE_CODE", MARKETLIFT_MARKET.django_language_code)
TIME_ZONE = env_text("DJANGO_TIME_ZONE", MARKETLIFT_MARKET.timezone)
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MARKETLIFT_FRONTEND_URL = env_text("MARKETLIFT_FRONTEND_URL", "https://marketlift.com.br")
MARKETLIFT_ADMIN_FRONTEND_URL = env_text(
    "MARKETLIFT_ADMIN_FRONTEND_URL", "https://dash.marketlift.com.br"
)
_BROWSER_ORIGINS = f"{MARKETLIFT_FRONTEND_URL},{MARKETLIFT_ADMIN_FRONTEND_URL}"

CORS_ALLOWED_ORIGINS = "https://marketlift.com.br,https://api.marketlift.com.br,https://dash.marketlift.com.br"
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = "https://marketlift.com.br,https://api.marketlift.com.br,https://dash.marketlift.com.br"

REDIS_URL = env_text("REDIS_URL", "redis://127.0.0.1:6379/0")


def redis_database_url(database: int) -> str:
    parsed = urlsplit(REDIS_URL)
    return parsed._replace(path=f"/{database}").geturl()


# One Redis endpoint is enough; logical DBs separate cache, Celery and Channels.
CHANNEL_REDIS_URL = redis_database_url(3)
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": os.getenv(
            "MARKETLIFT_CHANNEL_LAYER_BACKEND",
            "channels_redis.core.RedisChannelLayer",
        ),
        "CONFIG": {
            "hosts": [CHANNEL_REDIS_URL],
            "capacity": int(os.getenv("MARKETLIFT_CHANNEL_CAPACITY", "1000")),
            "expiry": int(os.getenv("MARKETLIFT_CHANNEL_EXPIRY_SECONDS", "60")),
        },
    }
}
MARKETLIFT_WEBSOCKET_ALLOWED_ORIGINS = env_list(
    "MARKETLIFT_WEBSOCKET_ALLOWED_ORIGINS",
    ",".join(CORS_ALLOWED_ORIGINS),
)
MARKETLIFT_WEBSOCKET_ACTION_RATE_LIMIT_PER_MINUTE = int(
    os.getenv("MARKETLIFT_WEBSOCKET_ACTION_RATE_LIMIT_PER_MINUTE", "180")
)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "marketlift_sessionid")
MARKETLIFT_ADMIN_SESSION_COOKIE_NAME = os.getenv(
    "MARKETLIFT_ADMIN_SESSION_COOKIE_NAME", "marketlift_admin_sessionid"
)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = IS_PRODUCTION
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = IS_PRODUCTION
CSRF_COOKIE_SAMESITE = "Lax"

CELERY_BROKER_URL = redis_database_url(1)
CELERY_RESULT_BACKEND = redis_database_url(2)
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = int(os.getenv("CELERY_TASK_TIME_LIMIT", "300"))
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "expire-due-seller-subscriptions": {
        "task": "subscriptions.tasks.expire_due_seller_subscriptions",
        "schedule": 3600.0,
    },
    "cleanup-expired-uploads": {
        "task": "uploads.tasks.cleanup_expired_uploads",
        "schedule": 21600.0,
    },
}

MEDIA_ROOT = Path(os.getenv("MARKETLIFT_MEDIA_ROOT", BASE_DIR / "media"))
MEDIA_URL = "/media/"

# Domain code talks only to logical storage aliases. Local development keeps
# the historical `default` alias so existing local uploads remain readable.
# When R2/S3-compatible credentials are present, new uploads stage in `temp` and
# are promoted to public/private/evidence after validation.
MARKETLIFT_STORAGE_BACKENDS = {
    "default": os.getenv(
        "MARKETLIFT_STORAGE_BACKEND",
        "uploads.storage.local.LocalStorageBackend",
    )
}
MARKETLIFT_LOCAL_UPLOAD_ROOT = Path(
    os.getenv("MARKETLIFT_LOCAL_UPLOAD_ROOT", BASE_DIR / ".marketlift-uploads")
)

R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "").strip()
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "").strip()
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL", "").strip()
if not R2_ENDPOINT_URL and R2_ACCOUNT_ID:
    R2_ENDPOINT_URL = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
R2_PUBLIC_BUCKET = os.getenv("R2_PUBLIC_BUCKET", "marketlift-public").strip()
# R2_MEDIA_BUCKET remains accepted as a compatibility alias for deployments that
# adopted the earlier env name before `R2_PRIVATE_BUCKET` was standardized.
R2_PRIVATE_BUCKET = os.getenv("R2_PRIVATE_BUCKET", "marketlift-private").strip()
R2_EVIDENCE_BUCKET = os.getenv("R2_EVIDENCE_BUCKET", "marketlift-evidence").strip()
R2_TEMP_BUCKET = os.getenv("R2_TEMP_BUCKET", "marketlift-temp").strip()
R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL", "").strip()

MARKETLIFT_S3_ENDPOINT_URL = R2_ENDPOINT_URL
MARKETLIFT_S3_ACCESS_KEY_ID = R2_ACCESS_KEY_ID
MARKETLIFT_S3_SECRET_ACCESS_KEY = R2_SECRET_ACCESS_KEY
MARKETLIFT_S3_REGION = os.getenv("R2_REGION", "auto").strip() or "auto"
MARKETLIFT_PUBLIC_ASSET_BASE_URL = os.getenv(
    "MARKETLIFT_PUBLIC_ASSET_BASE_URL", R2_PUBLIC_BASE_URL
).strip()
MARKETLIFT_PUBLIC_STORAGE_ALIAS = "public"
MARKETLIFT_PRESIGNED_UPLOAD_TTL_SECONDS = int(
    os.getenv("MARKETLIFT_PRESIGNED_UPLOAD_TTL_SECONDS", "900")
)
MARKETLIFT_PRESIGNED_DOWNLOAD_TTL_SECONDS = int(
    os.getenv("MARKETLIFT_PRESIGNED_DOWNLOAD_TTL_SECONDS", "300")
)

_r2_buckets = {
    "public": R2_PUBLIC_BUCKET,
    "private": R2_PRIVATE_BUCKET,
    "evidence": R2_EVIDENCE_BUCKET,
    "temp": R2_TEMP_BUCKET,
}
_r2_required_values = [
    R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY,
    R2_ENDPOINT_URL,
    *_r2_buckets.values(),
]
MARKETLIFT_R2_ANY_CONFIGURED = any(
    [R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ACCOUNT_ID, R2_ENDPOINT_URL]
)
MARKETLIFT_R2_CONFIGURED = all(_r2_required_values)
if MARKETLIFT_R2_CONFIGURED:
    _s3_backend = "uploads.storage.s3.S3CompatibleStorageBackend"
    MARKETLIFT_STORAGE_BACKENDS.update({alias: _s3_backend for alias in _r2_buckets})
    MARKETLIFT_STORAGE_BUCKETS = dict(_r2_buckets)
    MARKETLIFT_UPLOAD_STAGING_ALIAS = "temp"
    MARKETLIFT_UPLOAD_PURPOSE_ALIASES = {
        "listing_image": "public",
        "avatar": "public",
        "message_image": "private",
        "support_attachment": "private",
        "verification_document": "evidence",
        "verification_selfie": "evidence",
        "report_evidence": "evidence",
    }
else:
    MARKETLIFT_STORAGE_BUCKETS = {}
    MARKETLIFT_UPLOAD_STAGING_ALIAS = "default"
    MARKETLIFT_UPLOAD_PURPOSE_ALIASES = {
        purpose: "default"
        for purpose in (
            "listing_image",
            "avatar",
            "message_image",
            "support_attachment",
            "verification_document",
            "verification_selfie",
            "report_evidence",
        )
    }

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
}

EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com").strip()
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "").strip()
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "15"))

# Provider-backed capabilities are disabled for the initial production release.
# The frontend flags must only be enabled after these server-side flags and the
# corresponding provider certification are enabled together.
MARKETLIFT_PAYMENTS_ENABLED = env_bool("MARKETLIFT_PAYMENTS_ENABLED", False)
MARKETLIFT_IDENTITY_VERIFICATION_ENABLED = env_bool(
    "MARKETLIFT_IDENTITY_VERIFICATION_ENABLED",
    env_bool("MARKETLIFT_CPF_VERIFICATION_ENABLED", False),
)
# Compatibility alias for the existing Brazil frontend/config. New code should use
# MARKETLIFT_IDENTITY_VERIFICATION_ENABLED.
MARKETLIFT_CPF_VERIFICATION_ENABLED = MARKETLIFT_IDENTITY_VERIFICATION_ENABLED
MARKETLIFT_IDENTITY_VERIFICATION_PROVIDER = (
    os.getenv("MARKETLIFT_IDENTITY_VERIFICATION_PROVIDER", "disabled").strip().lower()
)
MARKETLIFT_IDENTITY_PROVIDER_READY = env_bool(
    "MARKETLIFT_IDENTITY_PROVIDER_READY", False
)

# Marketlift service-payment integration. Buyer -> seller transactions remain outside
# the platform. `mock` stays the safe default until a deployment explicitly enables
# its country provider.
MARKETLIFT_PAYMENT_PROVIDER = (
    os.getenv("MARKETLIFT_PAYMENT_PROVIDER", "auto").strip().lower()
)
MARKETLIFT_PAYMENT_METHODS = tuple(
    item.strip().lower()
    for item in env_list(
        "MARKETLIFT_PAYMENT_METHODS", ",".join(MARKETLIFT_MARKET_PAYMENT_METHODS)
    )
)
PAYMENT_MOCK_AUTO_APPROVE = env_bool("PAYMENT_MOCK_AUTO_APPROVE", True)
MERCADO_PAGO_ACCESS_TOKEN = os.getenv("MERCADO_PAGO_ACCESS_TOKEN", "")
MERCADO_PAGO_PUBLIC_KEY = os.getenv("MERCADO_PAGO_PUBLIC_KEY", "")
MERCADO_PAGO_WEBHOOK_SECRET = os.getenv("MERCADO_PAGO_WEBHOOK_SECRET", "")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "").strip()
PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "").strip()
PAYSTACK_API_BASE_URL = os.getenv(
    "PAYSTACK_API_BASE_URL", "https://api.paystack.co"
).rstrip("/")
PAYSTACK_CALLBACK_URL = os.getenv("PAYSTACK_CALLBACK_URL", "").strip()


# Production/security controls. These stay environment-driven so hosting providers can change.
DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL", "Marketlift <noreply@marketlift.com.br>"
)
MARKETLIFT_ADMIN_SESSION_ORIGINS = env_list(
    "MARKETLIFT_ADMIN_SESSION_ORIGINS", MARKETLIFT_ADMIN_FRONTEND_URL
)
# Keep localhost and 127.0.0.1 equivalent during local development without
# broadening the trusted origin to the marketplace port.
if not IS_PRODUCTION:
    for origin in list(MARKETLIFT_ADMIN_SESSION_ORIGINS):
        if "//localhost:" in origin:
            MARKETLIFT_ADMIN_SESSION_ORIGINS.append(
                origin.replace("//localhost:", "//127.0.0.1:")
            )
        elif "//127.0.0.1:" in origin:
            MARKETLIFT_ADMIN_SESSION_ORIGINS.append(
                origin.replace("//127.0.0.1:", "//localhost:")
            )
MARKETLIFT_ADMIN_SESSION_ORIGINS = list(dict.fromkeys(MARKETLIFT_ADMIN_SESSION_ORIGINS))
MARKETLIFT_ADMIN_MFA_REQUIRED = IS_PRODUCTION
MARKETLIFT_ADMIN_MFA_TTL_SECONDS = int(
    os.getenv("MARKETLIFT_ADMIN_MFA_TTL_SECONDS", "600")
)
SESSION_COOKIE_AGE = 1209600
SESSION_SAVE_EVERY_REQUEST = False
SECURE_SSL_REDIRECT = IS_PRODUCTION
SECURE_HSTS_SECONDS = 31536000 if IS_PRODUCTION else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = IS_PRODUCTION
SECURE_HSTS_PRELOAD = IS_PRODUCTION
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
USE_X_FORWARDED_HOST = False
MARKETLIFT_TRUST_PROXY_HEADERS = IS_PRODUCTION
MARKETLIFT_GRAPHQL_RATE_LIMIT_PER_MINUTE = int(
    os.getenv("MARKETLIFT_GRAPHQL_RATE_LIMIT_PER_MINUTE", "120")
)
MARKETLIFT_GRAPHQL_MAX_DEPTH = int(os.getenv("MARKETLIFT_GRAPHQL_MAX_DEPTH", "12"))
MARKETLIFT_GRAPHQL_MAX_TOKENS = int(os.getenv("MARKETLIFT_GRAPHQL_MAX_TOKENS", "5000"))
MARKETLIFT_GRAPHQL_MAX_ALIASES = int(os.getenv("MARKETLIFT_GRAPHQL_MAX_ALIASES", "30"))
MARKETLIFT_DISABLE_GRAPHQL_INTROSPECTION = env_bool(
    "MARKETLIFT_DISABLE_GRAPHQL_INTROSPECTION", IS_PRODUCTION
)
MARKETLIFT_GRAPHQL_IDE_ENABLED = env_bool(
    "MARKETLIFT_GRAPHQL_IDE_ENABLED", not IS_PRODUCTION
)

# Public marketplace search. The API contract is backend-neutral so an
# OpenSearch adapter can replace PostgreSQL later without changing clients.
MARKETLIFT_SEARCH_BACKEND = os.getenv(
    "MARKETLIFT_SEARCH_BACKEND",
    "marketlift.search.backends.postgres.PostgresListingSearchBackend",
)
MARKETLIFT_SEARCH_RATE_LIMIT_PER_MINUTE = int(
    os.getenv("MARKETLIFT_SEARCH_RATE_LIMIT_PER_MINUTE", "240")
)
MARKETLIFT_SEARCH_MAX_QUERY_LENGTH = int(
    os.getenv("MARKETLIFT_SEARCH_MAX_QUERY_LENGTH", "160")
)
MARKETLIFT_SEARCH_MAX_PAGE_SIZE = int(
    os.getenv("MARKETLIFT_SEARCH_MAX_PAGE_SIZE", "50")
)
MARKETLIFT_SEARCH_MAX_WINDOW = int(os.getenv("MARKETLIFT_SEARCH_MAX_WINDOW", "5000"))
MARKETLIFT_SEARCH_STATEMENT_TIMEOUT_MS = int(
    os.getenv("MARKETLIFT_SEARCH_STATEMENT_TIMEOUT_MS", "1500")
)

# Market-aware location/autocomplete/geocoding. The geocoder is country-scoped by
# the active market while listing/search domain logic stays provider-neutral.
MARKETLIFT_LOCATION_MAX_RADIUS_KM = float(
    os.getenv("MARKETLIFT_LOCATION_MAX_RADIUS_KM", "200")
)
MARKETLIFT_LOCATION_RATE_LIMIT_PER_MINUTE = int(
    os.getenv("MARKETLIFT_LOCATION_RATE_LIMIT_PER_MINUTE", "60")
)
MARKETLIFT_LOCATION_QUERY_MAX_LENGTH = int(
    os.getenv("MARKETLIFT_LOCATION_QUERY_MAX_LENGTH", "160")
)
MARKETLIFT_LOCATION_TOKEN_MAX_AGE_SECONDS = int(
    os.getenv("MARKETLIFT_LOCATION_TOKEN_MAX_AGE_SECONDS", "86400")
)
MARKETLIFT_REQUIRE_RESOLVED_LISTING_LOCATION = IS_PRODUCTION
MARKETLIFT_GEOCODER_BACKEND = os.getenv(
    "MARKETLIFT_GEOCODER_BACKEND",
    "marketlift.location.providers.nominatim.NominatimGeocoder",
)
MARKETLIFT_NOMINATIM_BASE_URL = os.getenv(
    "MARKETLIFT_NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org"
)
MARKETLIFT_GEOCODER_TIMEOUT_SECONDS = float(
    os.getenv("MARKETLIFT_GEOCODER_TIMEOUT_SECONDS", "4")
)
MARKETLIFT_GEOCODER_CACHE_SECONDS = int(
    os.getenv("MARKETLIFT_GEOCODER_CACHE_SECONDS", "86400")
)
MARKETLIFT_GEOCODER_LANGUAGE = env_text(
    "MARKETLIFT_GEOCODER_LANGUAGE", MARKETLIFT_MARKET.geocoder_language
)
MARKETLIFT_GEOCODER_USER_AGENT = os.getenv(
    "MARKETLIFT_GEOCODER_USER_AGENT", "Marketlift/0.1 development"
)
MARKETLIFT_IBGE_LOCATIONS_BASE_URL = os.getenv(
    "MARKETLIFT_IBGE_LOCATIONS_BASE_URL",
    "https://servicodados.ibge.gov.br/api/v1/localidades",
)
MARKETLIFT_LOCATION_CATALOG_CACHE_SECONDS = int(
    os.getenv("MARKETLIFT_LOCATION_CATALOG_CACHE_SECONDS", "604800")
)
MARKETLIFT_LOCATION_CATALOG_TIMEOUT_SECONDS = float(
    os.getenv("MARKETLIFT_LOCATION_CATALOG_TIMEOUT_SECONDS", "5")
)

if IS_PRODUCTION:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
DATA_UPLOAD_MAX_MEMORY_SIZE = int(
    os.getenv("DATA_UPLOAD_MAX_MEMORY_SIZE", str(2 * 1024 * 1024))
)
FILE_UPLOAD_MAX_MEMORY_SIZE = int(
    os.getenv("FILE_UPLOAD_MAX_MEMORY_SIZE", str(2 * 1024 * 1024))
)
MARKETLIFT_STRICT_UPLOAD_VALIDATION = env_bool(
    "MARKETLIFT_STRICT_UPLOAD_VALIDATION", True
)
MARKETLIFT_PROCESS_UPLOADS_ASYNC = env_bool("MARKETLIFT_PROCESS_UPLOADS_ASYNC", False)
MARKETLIFT_DJANGO_STORAGE_ALIAS = os.getenv(
    "MARKETLIFT_DJANGO_STORAGE_ALIAS", "marketlift_media"
)

CELERY_BEAT_SCHEDULE.update(
    {
        "expire-due-listings": {
            "task": "listings.tasks.expire_due_listings",
            "schedule": 3600.0,
        },
        "saved-search-alerts": {
            "task": "saved_searches.tasks.process_saved_search_alerts",
            "schedule": 900.0,
        },
        "notification-email-delivery": {
            "task": "notifications.tasks.deliver_pending_notification_emails",
            "schedule": 60.0,
        },
        "payment-reconciliation": {
            "task": "payments.tasks.reconcile_pending_payments",
            "schedule": 900.0,
        },
        "promotion-expiry-notifications": {
            "task": "promotions.tasks.notify_expired_promotions",
            "schedule": 3600.0,
        },
        "cleanup-expired-sessions": {
            "task": "marketlift.tasks.cleanup_expired_sessions",
            "schedule": 86400.0,
        },
    }
)

_media_storage_options = {
    "location": os.getenv(
        "MARKETLIFT_DJANGO_STORAGE_LOCATION", str(BASE_DIR / ".marketlift-remote")
    ),
    "base_url": os.getenv("MARKETLIFT_DJANGO_STORAGE_BASE_URL", "/media/"),
}
_extra_storage_options = os.getenv("MARKETLIFT_DJANGO_STORAGE_OPTIONS_JSON", "").strip()
if _extra_storage_options:
    try:
        parsed_options = json.loads(_extra_storage_options)
        if isinstance(parsed_options, dict):
            _media_storage_options.update(parsed_options)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "MARKETLIFT_DJANGO_STORAGE_OPTIONS_JSON must be valid JSON."
        ) from exc

STORAGES.setdefault(
    "marketlift_media",
    {
        "BACKEND": os.getenv(
            "MARKETLIFT_DJANGO_STORAGE_CLASS",
            "django.core.files.storage.FileSystemStorage",
        ),
        "OPTIONS": _media_storage_options,
    },
)

LOG_LEVEL = os.getenv("DJANGO_LOG_LEVEL", "INFO").upper()
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        }
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": os.getenv("DJANGO_REQUEST_LOG_LEVEL", "WARNING"),
            "propagate": False,
        },
        "marketlift": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}
