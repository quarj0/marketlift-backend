import strawberry
from django.core.exceptions import ValidationError
from marketlift.graphql.auth import require_user
from marketlift.graphql.errors import not_found_error, validation_error
from saved_searches.models import SavedSearch
from saved_searches.services import create_saved_search
from .inputs import SavedSearchInput
from .mappers import saved_search_to_type
from .types import SavedSearchType


@strawberry.type
class SavedSearchMutation:
    @strawberry.mutation
    def save_search(
        self, info: strawberry.Info, input: SavedSearchInput
    ) -> SavedSearchType:
        user = require_user(info)
        try:
            return saved_search_to_type(
                create_saved_search(
                    user=user,
                    name=input.name,
                    criteria=input.criteria or {},
                    alerts_enabled=input.alerts_enabled,
                )
            )
        except ValidationError as exc:
            raise validation_error(exc, code="SAVED_SEARCH_VALIDATION_ERROR")

    @strawberry.mutation
    def update_saved_search_alerts(
        self, info: strawberry.Info, id: strawberry.ID, enabled: bool
    ) -> SavedSearchType:
        user = require_user(info)
        try:
            x = user.saved_searches.get(pk=str(id))
        except SavedSearch.DoesNotExist:
            raise not_found_error("Saved search", code="SAVED_SEARCH_NOT_FOUND")
        x.alerts_enabled = enabled
        x.save(update_fields=("alerts_enabled", "updated_at"))
        return saved_search_to_type(x)

    @strawberry.mutation
    def delete_saved_search(self, info: strawberry.Info, id: strawberry.ID) -> bool:
        user = require_user(info)
        user.saved_searches.filter(pk=str(id)).delete()
        return True
