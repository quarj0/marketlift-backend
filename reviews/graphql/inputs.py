import strawberry


@strawberry.input
class CreateReviewInput:
    seller_id: strawberry.ID
    rating: int
    comment: str
    listing_id: strawberry.ID | None = None
