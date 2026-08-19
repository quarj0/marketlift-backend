"""Django settings for Marketlift."""

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


SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY", "django-insecure-marketlift-local-development-only"
)
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
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
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "marketlift_sessionid")
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", False)
SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", False)
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

# Marketlift service-payment integration. Product-sale payments remain outside Marketlift.
MARKETLIFT_PAYMENT_PROVIDER = os.getenv("MARKETLIFT_PAYMENT_PROVIDER", "mock")
PAYMENT_MOCK_AUTO_APPROVE = env_bool("PAYMENT_MOCK_AUTO_APPROVE", True)
MERCADO_PAGO_ACCESS_TOKEN = os.getenv("MERCADO_PAGO_ACCESS_TOKEN", "")
MERCADO_PAGO_PUBLIC_KEY = os.getenv("MERCADO_PAGO_PUBLIC_KEY", "")
MERCADO_PAGO_WEBHOOK_SECRET = os.getenv("MERCADO_PAGO_WEBHOOK_SECRET", "")
