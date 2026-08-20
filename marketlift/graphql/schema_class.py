from __future__ import annotations

from graphql import GraphQLError
from strawberry.schema import Schema

from .errors import DomainGraphQLError


def _is_domain_error(error: GraphQLError) -> bool:
    if isinstance(error, DomainGraphQLError):
        return True
    return isinstance(getattr(error, "original_error", None), DomainGraphQLError)


class MarketliftSchema(Schema):
    """Schema that does not print resolver tracebacks for expected domain errors."""

    def process_errors(self, errors, execution_context=None) -> None:
        unexpected = [error for error in errors if not _is_domain_error(error)]
        if unexpected:
            super().process_errors(unexpected, execution_context)
