from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from marketlift.search.service import search_listings
from marketlift.security.rate_limit import enforce_rate_limit

from .params import search_request_from_query_params
from .serializers import serialize_search_listing


def _drf_validation_error(exc: DjangoValidationError) -> DRFValidationError:
    if hasattr(exc, "message_dict"):
        return DRFValidationError(exc.message_dict)
    return DRFValidationError(getattr(exc, "messages", [str(exc)]))


class ListingSearchView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        enforce_rate_limit(
            request,
            "public-listing-search",
            limit=settings.MARKETLIFT_SEARCH_RATE_LIMIT_PER_MINUTE,
            window=60,
        )
        try:
            search_request = search_request_from_query_params(request.query_params)
            page = search_listings(search_request)
        except DjangoValidationError as exc:
            raise _drf_validation_error(exc) from exc

        parsed = page.parsed_query
        response = Response(
            {
                "query": parsed.original,
                "interpreted": parsed.interpreted_payload(),
                "relaxed": [item.as_dict() for item in page.relaxed],
                "totalCount": page.total_count,
                "nextCursor": page.next_cursor,
                "results": [serialize_search_listing(item) for item in page.items],
            }
        )
        # Text/filter searches are safe for short shared-edge caching. Exact user
        # coordinates are treated as private request data and must not enter a
        # shared CDN cache even though the result cards themselves are public.
        if search_request.latitude is not None:
            response["Cache-Control"] = "private, no-store"
        else:
            response["Cache-Control"] = "public, max-age=15, stale-while-revalidate=30"
        return response
