from __future__ import annotations

from django.conf import settings
from strawberry.django.views import GraphQLView

from .errors import DomainGraphQLError


def _is_domain_error(error) -> bool:
    if isinstance(error, DomainGraphQLError):
        return True
    return isinstance(getattr(error, "original_error", None), DomainGraphQLError)


class MarketliftGraphQLView(GraphQLView):
    """Normalize GraphQL errors and hide unexpected exception details in production."""

    def process_result(self, request, result):
        response = super().process_result(request, result)
        formatted_errors = (
            response.get("errors") if isinstance(response, dict) else None
        )
        if not formatted_errors or not getattr(result, "errors", None):
            return response

        for formatted, error in zip(formatted_errors, result.errors, strict=False):
            if _is_domain_error(error):
                continue

            original = getattr(error, "original_error", None)
            if original is None:
                extensions = formatted.setdefault("extensions", {})
                extensions.setdefault("code", "GRAPHQL_REQUEST_ERROR")
                extensions.setdefault("status", 400)
                continue

            if settings.IS_PRODUCTION:
                formatted["message"] = "An unexpected error occurred."
            formatted["extensions"] = {
                "code": "INTERNAL_SERVER_ERROR",
                "status": 500,
            }

        return response
