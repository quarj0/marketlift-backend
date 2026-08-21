import strawberry


@strawberry.type
class LocationType:
    country_code: str | None = None
    state: str = ""
    state_code: str = ""
    city: str = ""
    district: str | None = None
