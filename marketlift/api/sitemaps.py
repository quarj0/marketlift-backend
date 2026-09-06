"""Public sitemap partitions use indexed UUID ranges, never search result windows."""

import uuid
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import CharField, Count, Max
from django.db.models.functions import Cast, Substr
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from listings.models import Listing
from marketlift.security.rate_limit import enforce_rate_limit
from marketlift.markets.service import normalize_enabled_country_code


class SitemapView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        enforce_rate_limit(request, "public-sitemap", limit=180, window=60)
        try:
            country = normalize_enabled_country_code(
                request.query_params.get("countryCode", "BR")
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc
        bucket = request.query_params.get("bucket")
        if bucket is not None and (
            len(bucket) != 3 or any(c not in "0123456789abcdef" for c in bucket)
        ):
            raise ValidationError(
                {"bucket": "Expected a three-character hexadecimal partition."}
            )
        key = f'marketlift:sitemap:v1:{country}:{bucket or "index"}'
        payload = cache.get(key)
        if payload is None:
            qs = Listing.objects.public().filter(country_code=country)
            if bucket is None:
                rows = (
                    qs.order_by()
                    .annotate(bucket=Substr(Cast("id", CharField()), 1, 3))
                    .values("bucket")
                    .annotate(count=Count("id"), modified=Max("updated_at"))
                    .order_by("bucket")
                )
                payload = {"partitions": list(rows)}
            else:
                first = int(bucket, 16) << 116
                qs = qs.filter(id__gte=uuid.UUID(int=first))
                if bucket != "fff":
                    qs = qs.filter(id__lt=uuid.UUID(int=first + (1 << 116)))
                items = list(qs.order_by("id").values("slug", "updated_at")[:50001])
                if len(items) > 50000:
                    # Fail visibly rather than silently dropping crawlable URLs.
                    return Response(
                        {"detail": "Sitemap partition capacity exceeded."}, status=503
                    )
                payload = {"listings": items}
            cache.set(key, payload, timeout=900)
        response = Response(payload)
        response["Cache-Control"] = "public, max-age=900, stale-while-revalidate=900"
        return response
