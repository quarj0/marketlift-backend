"""Request correlation and bounded, credential-free HTTP timing logs."""

import logging
import re
import time
import uuid

logger = logging.getLogger("marketlift.http")
_REQUEST_ID = re.compile(r"^[a-zA-Z0-9_-]{8,64}$")


class RequestObservabilityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        supplied = request.headers.get("X-Request-ID", "")
        request.request_id = (
            supplied if _REQUEST_ID.fullmatch(supplied) else uuid.uuid4().hex
        )
        started = time.monotonic()
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        # Route patterns avoid logging query strings, email addresses or message bodies.
        route = getattr(getattr(request, "resolver_match", None), "route", "unmatched")
        logger.info(
            "http request_id=%s method=%s route=%s status=%s duration_ms=%.1f",
            request.request_id,
            request.method,
            route,
            response.status_code,
            (time.monotonic() - started) * 1000,
        )
        return response
