from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from marketlift.location.service import geocode_locations, reverse_geocode_location
from marketlift.location.tokens import encode_location_token
from marketlift.location.validators import validate_coordinates
from marketlift.security.rate_limit import enforce_rate_limit


def _drf(exc: DjangoValidationError) -> DRFValidationError:
    if hasattr(exc, "message_dict"):
        return DRFValidationError(exc.message_dict)
    return DRFValidationError(getattr(exc, "messages", [str(exc)]))


def _limit(raw) -> int:
    try:
        return max(1, min(int(raw or 5), 8))
    except (TypeError, ValueError) as exc:
        raise DRFValidationError({"limit": "Must be an integer between 1 and 8."}) from exc


class LocationSearchView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        enforce_rate_limit(
            request,
            "public-location-search",
            limit=settings.MARKETLIFT_LOCATION_RATE_LIMIT_PER_MINUTE,
            window=60,
        )
        try:
            rows = geocode_locations(request.query_params.get("q", ""), limit=_limit(request.query_params.get("limit")))
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        return Response({"results": [row.as_dict(token=encode_location_token(row)) for row in rows]})


class LocationReverseView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        enforce_rate_limit(
            request,
            "public-location-reverse",
            limit=settings.MARKETLIFT_LOCATION_RATE_LIMIT_PER_MINUTE,
            window=60,
        )
        try:
            lat, lng = validate_coordinates(request.query_params.get("lat"), request.query_params.get("lng"), required=True)
            row = reverse_geocode_location(lat, lng)
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        if row is None:
            return Response({"result": None})
        return Response({"result": row.as_dict(token=encode_location_token(row))})
