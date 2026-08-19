import strawberry


@strawberry.type
class HealthQuery:
    @strawberry.field
    def health(self) -> str:
        return "ok"
