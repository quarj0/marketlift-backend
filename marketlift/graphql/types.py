import strawberry


@strawberry.type
class LocationType:
    state: str
    state_code: str
    city: str
    district: str | None = None
