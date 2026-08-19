from .types import ReviewType, SellerReputationType
from reviews.services import seller_reputation


def review_to_type(review):
    return ReviewType(
        id=str(review.id),
        seller_id=str(review.seller_id),
        seller_name=str(review.seller),
        seller_avatar=(review.seller.user.avatar_url or None),
        reviewer_id=str(review.reviewer_id),
        reviewer_name=review.reviewer.full_name or review.reviewer.email,
        listing_id=str(review.listing_id) if review.listing_id else None,
        listing_title=review.listing.title if review.listing_id else None,
        rating=review.rating,
        comment=review.comment,
        date=review.created_at,
        seller_reply=review.seller_reply or None,
    )


def reputation_to_type(seller):
    x = seller_reputation(seller)
    d = x["distribution"]
    return SellerReputationType(
        average=x["average"],
        total=x["total"],
        positive_percent=x["positive_percent"],
        one_star=d[1],
        two_star=d[2],
        three_star=d[3],
        four_star=d[4],
        five_star=d[5],
    )
