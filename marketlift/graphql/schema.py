import strawberry
from strawberry.extensions import MaxAliasesLimiter, MaxTokensLimiter, QueryDepthLimiter
from strawberry.tools import merge_types
from strawberry_django.optimizer import DjangoOptimizerExtension

from .registry import MUTATION_TYPES, QUERY_TYPES

Query = merge_types("Query", QUERY_TYPES)
Mutation = merge_types("Mutation", MUTATION_TYPES)

schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[
        DjangoOptimizerExtension,
        lambda: QueryDepthLimiter(max_depth=12),
        lambda: MaxTokensLimiter(max_token_count=5000),
        lambda: MaxAliasesLimiter(max_alias_count=30),
    ],
)
