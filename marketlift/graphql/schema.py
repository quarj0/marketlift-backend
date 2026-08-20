from django.conf import settings
from strawberry.extensions import (
    DisableIntrospection,
    MaxAliasesLimiter,
    MaxTokensLimiter,
    QueryDepthLimiter,
)
from strawberry.tools import merge_types
from strawberry_django.optimizer import DjangoOptimizerExtension

from .registry import MUTATION_TYPES, QUERY_TYPES
from .schema_class import MarketliftSchema

Query = merge_types("Query", QUERY_TYPES)
Mutation = merge_types("Mutation", MUTATION_TYPES)

extensions = [
    DjangoOptimizerExtension,
    lambda: QueryDepthLimiter(max_depth=settings.MARKETLIFT_GRAPHQL_MAX_DEPTH),
    lambda: MaxTokensLimiter(max_token_count=settings.MARKETLIFT_GRAPHQL_MAX_TOKENS),
    lambda: MaxAliasesLimiter(max_alias_count=settings.MARKETLIFT_GRAPHQL_MAX_ALIASES),
]
if settings.MARKETLIFT_DISABLE_GRAPHQL_INTROSPECTION:
    extensions.append(DisableIntrospection)

schema = MarketliftSchema(query=Query, mutation=Mutation, extensions=extensions)
