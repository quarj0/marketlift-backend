import logging

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse

from .rate_limit import client_ip

logger = logging.getLogger(__name__)


class SecurityRateLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.rstrip("/") == "/graphql":
            ident = str(
                getattr(getattr(request, "user", None), "pk", "") or client_ip(request)
            )
            key = f"ml:gql:{ident}"
            try:
                if cache.add(key, 1, timeout=60):
                    count = 1
                else:
                    try:
                        count = cache.incr(key)
                    except ValueError:
                        count = 1
                        cache.set(key, 1, timeout=60)
                if count > settings.MARKETLIFT_GRAPHQL_RATE_LIMIT_PER_MINUTE:
                    return JsonResponse(
                        {"errors": [{"message": "GraphQL rate limit exceeded."}]},
                        status=429,
                    )
            except Exception:
                logger.warning("GraphQL rate-limit cache unavailable", exc_info=True)
        return self.get_response(request)


class MaintenanceModeMiddleware:
    ALWAYS_AVAILABLE_PREFIXES = (
        "/admin/",
        "/api/v1/health/",
        "/api/v1/ready/",
        "/api/v1/webhooks/",
        "/api/v1/auth/csrf/",
        "/api/v1/auth/session/",
        "/api/v1/auth/admin-login/",
        "/api/v1/auth/admin-login/verify/",
        "/api/v1/auth/admin-invite/accept/",
        "/api/v1/auth/logout/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(self.ALWAYS_AVAILABLE_PREFIXES):
            return self.get_response(request)

        maintenance = None
        try:
            maintenance = cache.get("ml:platform:maintenance")
        except Exception:
            pass
        if maintenance is None:
            try:
                from platform_settings.models import PlatformConfiguration

                maintenance = PlatformConfiguration.load().maintenance_mode
                try:
                    cache.set("ml:platform:maintenance", bool(maintenance), timeout=30)
                except Exception:
                    pass
            except Exception:
                maintenance = False

        if maintenance and not (
            getattr(request, "user", None)
            and request.user.is_authenticated
            and request.user.is_staff
        ):
            return JsonResponse(
                {"detail": "Marketlift is temporarily in maintenance mode."}, status=503
            )
        return self.get_response(request)
