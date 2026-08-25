from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from listings.models import Listing
from marketlift.location.catalog import brazil_cities, brazil_state_payload
from marketlift.location.service import geocode_locations, reverse_geocode_location
from marketlift.location.tokens import encode_location_token
from marketlift.location.validators import normalize_country_code, validate_coordinates
from marketlift.locations import BRAZIL_REGIONS
from marketlift.markets.service import profile_for_country_code, default_country_code
from marketlift.security.rate_limit import enforce_rate_limit


def _drf(exc: DjangoValidationError) -> DRFValidationError:
    if hasattr(exc, "message_dict"):
        return DRFValidationError(exc.message_dict)
    return DRFValidationError(getattr(exc, "messages", [str(exc)]))


def _limit(raw, *, default=5, maximum=100) -> int:
    try:
        return max(1, min(int(raw or default), maximum))
    except (TypeError, ValueError) as exc:
        raise DRFValidationError(
            {"limit": f"Must be an integer between 1 and {maximum}."}
        ) from exc


def _location_rate_limit(request, key: str):
    enforce_rate_limit(
        request,
        key,
        limit=settings.MARKETLIFT_LOCATION_RATE_LIMIT_PER_MINUTE,
        window=60,
    )


def _country(request) -> str:
    raw = (
        request.query_params.get("country")
        or request.query_params.get("countryCode")
        or default_country_code()
    )
    try:
        code = normalize_country_code(raw)
        return profile_for_country_code(code).country_code
    except DjangoValidationError as exc:
        raise _drf(exc) from exc


class LocationRegionsView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        country = _country(request)
        if country != "BR":
            return Response({"regions": [], "mode": "geocoder", "countryCode": country})
        return Response(
            {
                "regions": [
                    {"code": code, "name": name}
                    for code, name in BRAZIL_REGIONS.items()
                ],
                "mode": "catalog",
                "countryCode": "BR",
            }
        )


class LocationStatesView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        country = _country(request)
        if country == "BR":
            try:
                rows = brazil_state_payload(
                    (request.query_params.get("region") or "").strip() or None
                )
            except DjangoValidationError as exc:
                raise _drf(exc) from exc
            return Response({"states": rows, "mode": "catalog", "countryCode": country})

        # For geocoder-driven countries this endpoint remains useful after inventory
        # exists, without pretending we maintain a complete government boundary catalog.
        qs = (
            Listing.objects.public()
            .filter(country_code=country)
            .exclude(state="")
            .values("state", "state_code")
            .order_by("state")
            .distinct()[:200]
        )
        return Response(
            {
                "states": [
                    {"code": row["state_code"], "name": row["state"]} for row in qs
                ],
                "mode": "inventory",
                "countryCode": country,
            }
        )


class LocationCitiesView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        _location_rate_limit(request, "public-location-cities")
        country = _country(request)
        state = (request.query_params.get("state") or "").strip().upper()
        query = (request.query_params.get("q") or "").strip()
        limit = _limit(request.query_params.get("limit"), default=80, maximum=200)

        if country == "BR":
            if not state:
                raise DRFValidationError({"state": "Select a state first."})
            try:
                cities = brazil_cities(state, query=query, limit=limit)
            except DjangoValidationError as exc:
                raise _drf(exc) from exc
            return Response(
                {"cities": cities, "mode": "catalog", "countryCode": country}
            )

        qs = Listing.objects.public().filter(country_code=country).exclude(city="")
        if state:
            qs = qs.filter(state_code__iexact=state)
        if query:
            qs = qs.filter(city__icontains=query)
        cities = list(
            qs.order_by("city").values_list("city", flat=True).distinct()[:limit]
        )
        return Response({"cities": cities, "mode": "inventory", "countryCode": country})


class NeighborhoodSuggestionsView(APIView):
    """Autocomplete neighborhood/district names already present in inventory."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        _location_rate_limit(request, "public-location-neighborhoods")
        country = _country(request)
        state_code = (request.query_params.get("state") or "").strip().upper()
        city = (request.query_params.get("city") or "").strip()
        query = (request.query_params.get("q") or "").strip()

        if not city:
            return Response({"suggestions": []})

        qs = (
            Listing.objects.public()
            .filter(country_code=country, city__iexact=city)
            .exclude(district="")
        )
        if state_code:
            qs = qs.filter(state_code__iexact=state_code)
        if query:
            qs = qs.filter(district__icontains=query)

        values = list(
            qs.order_by("district").values_list("district", flat=True).distinct()[:40]
        )
        return Response({"suggestions": values})


class LocationSearchView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        _location_rate_limit(request, "public-location-search")
        country = _country(request)
        try:
            rows = geocode_locations(
                request.query_params.get("q", ""),
                limit=_limit(request.query_params.get("limit"), default=5, maximum=8),
                country_code=country,
            )
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        rows = [row for row in rows if (row.country_code or "").upper() == country]
        return Response(
            {
                "results": [
                    row.as_dict(token=encode_location_token(row)) for row in rows
                ],
                "countryCode": country,
            }
        )


class LocationReverseView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        _location_rate_limit(request, "public-location-reverse")
        country = _country(request)
        try:
            lat, lng = validate_coordinates(
                request.query_params.get("lat"),
                request.query_params.get("lng"),
                required=True,
            )
            row = reverse_geocode_location(lat, lng)
        except DjangoValidationError as exc:
            raise _drf(exc) from exc
        if row is None or (row.country_code or "").upper() != country:
            return Response({"result": None, "countryCode": country})
        return Response(
            {
                "result": row.as_dict(token=encode_location_token(row)),
                "countryCode": country,
            }
        )
