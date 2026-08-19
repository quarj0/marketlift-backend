from django.core.cache import cache
from django.db import connection
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import HTTP_503_SERVICE_UNAVAILABLE


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    return Response({"status": "ok", "service": "marketlift"})


@api_view(["GET"])
@permission_classes([AllowAny])
def readiness(request):
    checks: dict[str, str] = {}

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"

    try:
        cache.set("marketlift:readiness", "ok", timeout=10)
        checks["redis"] = "ok" if cache.get("marketlift:readiness") == "ok" else "unavailable"
    except Exception:
        checks["redis"] = "unavailable"

    ready = all(value == "ok" for value in checks.values())
    return Response(
        {"status": "ok" if ready else "unavailable", "checks": checks},
        status=200 if ready else HTTP_503_SERVICE_UNAVAILABLE,
    )
