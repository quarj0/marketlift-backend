import hashlib
import json
import logging
import time
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.sessions.backends.base import UpdateError
from django.contrib.sessions.exceptions import SessionInterrupted
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.cache import cache
from django.http import JsonResponse
from django.utils.cache import patch_vary_headers
from django.utils.http import http_date
from graphql import FieldNode, OperationType, get_operation_ast, parse

from .rate_limit import client_ip

logger = logging.getLogger(__name__)


def _origin(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    host = parsed.hostname.lower()
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme.lower()}://{host}{port}"


def _admin_session_origins() -> set[str]:
    configured = getattr(settings, "MARKETLIFT_ADMIN_SESSION_ORIGINS", [])
    return {_origin(item) for item in configured if _origin(item)}


def _session_surface(request) -> str:
    # Browser Origin is authoritative because JavaScript cannot spoof it. This
    # prevents marketplace code from opting itself into an administrator session
    # merely by sending a custom request header.
    request_origin = _origin(request.headers.get("Origin"))
    if request_origin:
        return "admin" if request_origin in _admin_session_origins() else "marketplace"

    # Non-browser clients and automated tests can opt into the admin surface.
    # Admin login endpoints are also admin-scoped when no Origin header exists.
    if (
        request.path.startswith("/api/v1/auth/admin-login/")
        or request.path.rstrip("/") == "/api/v1/auth/admin-login"
    ):
        return "admin"
    if request.headers.get("X-Marketlift-Surface", "").strip().lower() == "admin":
        return "admin"
    return "marketplace"


class ClientScopedSessionMiddleware(SessionMiddleware):
    """Use independent Django sessions for marketplace and admin surfaces.

    Cookies are scoped by name rather than browser port (cookies do not have a
    port boundary). The trusted request Origin chooses which cookie backs
    ``request.session``. Both surfaces still authenticate against the same user
    model and session store.
    """

    def __init__(self, get_response):
        # Subclass Django's SessionMiddleware so Django's admin/system checks and
        # middleware ordering semantics continue to recognize this as the normal
        # session layer. Only the cookie name selection is customized.
        super().__init__(get_response)

    @staticmethod
    def cookie_name_for(request) -> str:
        if _session_surface(request) == "admin":
            return settings.MARKETLIFT_ADMIN_SESSION_COOKIE_NAME
        return settings.SESSION_COOKIE_NAME

    def process_request(self, request):
        cookie_name = self.cookie_name_for(request)
        request.marketlift_session_surface = _session_surface(request)
        request.marketlift_session_cookie_name = cookie_name
        session_key = request.COOKIES.get(cookie_name)
        request.session = self.SessionStore(session_key)

    def process_response(self, request, response):
        try:
            accessed = request.session.accessed
            modified = request.session.modified
            empty = request.session.is_empty()
        except AttributeError:
            return response

        cookie_name = getattr(
            request,
            "marketlift_session_cookie_name",
            settings.SESSION_COOKIE_NAME,
        )

        if cookie_name in request.COOKIES and empty:
            response.delete_cookie(
                cookie_name,
                path=settings.SESSION_COOKIE_PATH,
                domain=settings.SESSION_COOKIE_DOMAIN,
                samesite=settings.SESSION_COOKIE_SAMESITE,
            )
            patch_vary_headers(response, ("Cookie",))
            return response

        if accessed:
            patch_vary_headers(response, ("Cookie",))

        if (modified or settings.SESSION_SAVE_EVERY_REQUEST) and not empty:
            if request.session.get_expire_at_browser_close():
                max_age = None
                expires = None
            else:
                max_age = request.session.get_expiry_age()
                expires = http_date(time.time() + max_age)

            if response.status_code < 500:
                try:
                    request.session.save()
                except UpdateError as exc:
                    raise SessionInterrupted(
                        "The request's session was deleted before the request completed."
                    ) from exc
                response.set_cookie(
                    cookie_name,
                    request.session.session_key,
                    max_age=max_age,
                    expires=expires,
                    domain=settings.SESSION_COOKIE_DOMAIN,
                    path=settings.SESSION_COOKIE_PATH,
                    secure=settings.SESSION_COOKIE_SECURE or None,
                    httponly=settings.SESSION_COOKIE_HTTPONLY or None,
                    samesite=settings.SESSION_COOKIE_SAMESITE,
                )
        return response


def _graphql_mutation_scope(request) -> str | None:
    """Return a stable scope for a GraphQL mutation, otherwise ``None``.

    Dashboard/read-only queries deliberately bypass the request-count limiter.
    Mutation scopes are based on real root field names (not aliases or operation
    labels), so clients cannot evade the limiter simply by renaming an operation.
    """

    if request.method.upper() != "POST":
        return None
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        return None
    operation_name = payload.get("operationName")
    if operation_name is not None and not isinstance(operation_name, str):
        return None
    try:
        document = parse(query)
        operation = get_operation_ast(document, operation_name)
    except Exception:
        # Let the GraphQL view return its normal syntax/validation response.
        return None
    if operation is None or operation.operation != OperationType.MUTATION:
        return None

    fields = sorted(
        {
            selection.name.value
            for selection in operation.selection_set.selections
            if isinstance(selection, FieldNode)
        }
    )
    return ",".join(fields) if fields else "anonymous"


class SecurityRateLimitMiddleware:
    """Protect GraphQL writes without throttling dashboard/read queries."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.rstrip("/") == "/graphql":
            mutation_scope = _graphql_mutation_scope(request)
            if mutation_scope:
                ident = str(
                    getattr(getattr(request, "user", None), "pk", "")
                    or client_ip(request)
                )
                raw = f"{ident}:{mutation_scope}".encode()
                key = "ml:gql:mutation:" + hashlib.sha256(raw).hexdigest()
                try:
                    if cache.add(key, 1, timeout=60):
                        count = 1
                    else:
                        try:
                            count = cache.incr(key)
                        except ValueError:
                            count = 1
                            cache.set(key, 1, timeout=60)
                    if (
                        count
                        > settings.MARKETLIFT_GRAPHQL_MUTATION_RATE_LIMIT_PER_MINUTE
                    ):
                        return JsonResponse(
                            {
                                "errors": [
                                    {
                                        "message": "Too many attempts for this action. Try again shortly.",
                                        "extensions": {
                                            "code": "GRAPHQL_MUTATION_RATE_LIMITED",
                                            "status": 429,
                                        },
                                    }
                                ]
                            },
                            status=429,
                        )
                except Exception:
                    logger.warning(
                        "GraphQL mutation rate-limit cache unavailable",
                        exc_info=True,
                    )
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
