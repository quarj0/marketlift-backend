"""Django settings for Marketlift."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [
        item.strip() for item in os.getenv(name, default).split(",") if item.strip()
    ]


MARKETLIFT_ENV = os.getenv("MARKETLIFT_ENV", "development").strip().lower()
IS_PRODUCTION = MARKETLIFT_ENV in {"production", "prod"}

SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY", "django-insecure-marketlift-local-development-only"
)
SECRET_KEY_FALLBACKS = env_list("DJANGO_SECRET_KEY_FALLBACKS")
DEBUG = env_bool("DJANGO_DEBUG", not IS_PRODUCTION)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

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
    "django.contrib.sessions.middleware.SessionMiddleware",
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

DATABASES = {
    "default": {
        # Provider-neutral database configuration. Supabase, Neon, a local
        # Docker PostgreSQL server, or any other compatible host can supply
        # these values without changing application code.
        "ENGINE": os.getenv("DB_ENGINE", "django.db.backends.postgresql"),
        "NAME": os.getenv("DB_NAME", os.getenv("POSTGRES_DB", "marketlift")),
        "USER": os.getenv("DB_USER", os.getenv("POSTGRES_USER", "marketlift")),
        "PASSWORD": os.getenv(
            "DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", "marketlift")
        ),
        "HOST": os.getenv("DB_HOST", os.getenv("POSTGRES_HOST", "127.0.0.1")),
        "PORT": os.getenv("DB_PORT", os.getenv("POSTGRES_PORT", "5433")),
        "CONN_MAX_AGE": int(
            os.getenv("DB_CONN_MAX_AGE", os.getenv("POSTGRES_CONN_MAX_AGE", "60"))
        ),
        "CONN_HEALTH_CHECKS": env_bool("DB_CONN_HEALTH_CHECKS", True),
    }
}

DB_SSLMODE = os.getenv("DB_SSLMODE", "").strip()
if DB_SSLMODE and DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
    DATABASES["default"]["OPTIONS"] = {"sslmode": DB_SSLMODE}


AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "America/Sao_Paulo")
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

CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001",
)
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001",
)

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

# Realtime transport. Redis is an implementation detail of the channel layer and
# can point at any compatible managed/self-hosted Redis endpoint. Database and
# object-storage providers remain independent from realtime delivery.
CHANNEL_REDIS_URL = os.getenv("CHANNEL_REDIS_URL", "redis://127.0.0.1:6379/3")
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
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", IS_PRODUCTION)
SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", IS_PRODUCTION)
CSRF_COOKIE_SAMESITE = os.getenv("CSRF_COOKIE_SAMESITE", "Lax")

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/1")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/2")
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

# Domain code talks to a logical storage alias only. Swap this dotted class
# path later without changing listings, messaging, verification, or reports.
MARKETLIFT_STORAGE_BACKENDS = {
    "default": os.getenv(
        "MARKETLIFT_STORAGE_BACKEND",
        "uploads.storage.local.LocalStorageBackend",
    )
}
MARKETLIFT_LOCAL_UPLOAD_ROOT = Path(
    os.getenv("MARKETLIFT_LOCAL_UPLOAD_ROOT", BASE_DIR / ".marketlift-uploads")
)

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
}

EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)

# Marketlift service-payment integration. Product-sale payments remain outside Marketlift V1.
MARKETLIFT_PAYMENT_PROVIDER = os.getenv("MARKETLIFT_PAYMENT_PROVIDER", "mock")
PAYMENT_MOCK_AUTO_APPROVE = env_bool("PAYMENT_MOCK_AUTO_APPROVE", True)
MERCADO_PAGO_ACCESS_TOKEN = os.getenv("MERCADO_PAGO_ACCESS_TOKEN", "")
MERCADO_PAGO_PUBLIC_KEY = os.getenv("MERCADO_PAGO_PUBLIC_KEY", "")
MERCADO_PAGO_WEBHOOK_SECRET = os.getenv("MERCADO_PAGO_WEBHOOK_SECRET", "")


# Production/security controls. These stay environment-driven so hosting providers can change.
DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL", "Marketlift <noreply@marketlift.local>"
)
MARKETLIFT_FRONTEND_URL = os.getenv("MARKETLIFT_FRONTEND_URL", "http://localhost:3000")
MARKETLIFT_ADMIN_FRONTEND_URL = os.getenv(
    "MARKETLIFT_ADMIN_FRONTEND_URL", "http://localhost:3001"
)
MARKETLIFT_ADMIN_MFA_REQUIRED = env_bool("MARKETLIFT_ADMIN_MFA_REQUIRED", IS_PRODUCTION)
MARKETLIFT_ADMIN_MFA_TTL_SECONDS = int(
    os.getenv("MARKETLIFT_ADMIN_MFA_TTL_SECONDS", "600")
)
SESSION_COOKIE_AGE = int(os.getenv("SESSION_COOKIE_AGE", "1209600"))
SESSION_SAVE_EVERY_REQUEST = env_bool("SESSION_SAVE_EVERY_REQUEST", False)
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", IS_PRODUCTION)
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
USE_X_FORWARDED_HOST = env_bool("USE_X_FORWARDED_HOST", False)
MARKETLIFT_TRUST_PROXY_HEADERS = env_bool("MARKETLIFT_TRUST_PROXY_HEADERS", False)
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
if env_bool("SECURE_PROXY_SSL_HEADER_ENABLED", False):
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
