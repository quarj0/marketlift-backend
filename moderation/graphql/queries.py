import strawberry
from marketlift.graphql.auth import require_staff
from moderation.models import ModerationCase
from .mappers import moderation_case_to_type
from .types import ModerationCaseType


@strawberry.type
class ModerationQuery:
    @strawberry.field
    def moderation_queue(
        self,
        info: strawberry.Info,
        include_final: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ModerationCaseType]:
        require_staff(info)
        qs = ModerationCase.objects.select_related("listing", "decided_by")
        if not include_final:
            qs = qs.filter(status=ModerationCase.Status.REVIEW)
        start = max(0, offset)
        end = start + max(1, min(limit, 100))
        return [moderation_case_to_type(c) for c in qs[start:end]]
