import hashlib
import logging

from django.core.cache import cache
from rest_framework.exceptions import Throttled

logger = logging.getLogger(__name__)


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",", 1)[0].strip()
    return forwarded or request.META.get("REMOTE_ADDR") or "unknown"


def _identity(request):
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        return f"u:{user.pk}"
    return f"ip:{client_ip(request)}"


def enforce_rate_limit(request, scope, *, limit, window):
    raw = f"{scope}:{_identity(request)}".encode()
    key = "ml:rl:" + hashlib.sha256(raw).hexdigest()
    try:
        if cache.add(key, 1, timeout=window):
            return
        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=window)
            count = 1
    except Exception:
        # Rate limiting is a protection layer, not a reason to make the whole
        # marketplace unavailable if the cache has a short outage.
        logger.exception("Rate-limit cache unavailable for scope %s", scope)
        return

    if count > limit:
        raise Throttled(wait=window, detail="Too many requests. Try again later.")
