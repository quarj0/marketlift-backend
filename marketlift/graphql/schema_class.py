from __future__ import annotations

from graphql import GraphQLError
from strawberry.schema import Schema

from .errors import normalize_expected_error


def _is_expected_error(error: GraphQLError) -> bool:
    return normalize_expected_error(error) is not None


class MarketliftSchema(Schema):
    """Schema that only logs genuinely unexpected resolver failures."""

    def process_errors(self, errors, execution_context=None) -> None:
        unexpected = [error for error in errors if not _is_expected_error(error)]
        if unexpected:
            super().process_errors(unexpected, execution_context)
