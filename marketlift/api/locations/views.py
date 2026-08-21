from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from listings.models import Listing


class NeighborhoodSuggestionsView(APIView):
    """Return real neighborhood/district names already used in public listings.

    Neighborhood names are not centrally standardized across Brazil, so Marketlift
    treats this as autocomplete rather than a closed enum. Sellers can still type a
    new neighborhood while buyers benefit from suggestions that match marketplace
    inventory.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        state_code = (request.query_params.get("state") or "").strip().upper()
        city = (request.query_params.get("city") or "").strip()
        query = (request.query_params.get("q") or "").strip()

        if not state_code or not city:
            return Response({"suggestions": []})

        qs = (
            Listing.objects.public()
            .filter(state_code__iexact=state_code, city__iexact=city)
            .exclude(district="")
        )
        if query:
            qs = qs.filter(district__icontains=query)

        values = list(
            qs.order_by("district").values_list("district", flat=True).distinct()[:40]
        )
        return Response({"suggestions": values})
