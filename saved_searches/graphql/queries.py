import strawberry
from marketlift.graphql.auth import require_user
from .types import SavedSearchType
from .mappers import saved_search_to_type


@strawberry.type
class SavedSearchQuery:
    @strawberry.field
    def my_saved_searches(self, info: strawberry.Info) -> list[SavedSearchType]:
        user = require_user(info)
        return [
            saved_search_to_type(x) for x in user.saved_searches.filter(active=True)
        ]
