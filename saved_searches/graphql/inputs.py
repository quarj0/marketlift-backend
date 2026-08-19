import strawberry
from strawberry.scalars import JSON


@strawberry.input
class SavedSearchInput:
    name: str = ""
    criteria: JSON | None = None
    alerts_enabled: bool = True
