from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.utils import timezone
from audit.services import record_audit_event
from notifications.services import create_notification
from .models import SellerReview


def _refresh_cached_reputation(seller):
    x = seller_reputation(seller)
    seller.rating_average = x["average"]
    seller.review_count = x["total"]
    seller.positive_review_percent = x["positive_percent"]
    seller.save(
        update_fields=(
            "rating_average",
            "review_count",
            "positive_review_percent",
            "updated_at",
        )
    )
    return x


def seller_reputation(seller):
    agg = seller.reviews.filter(hidden_at__isnull=True).aggregate(
        average=Avg("rating"), total=Count("id")
    )
    dist = {i: 0 for i in range(1, 6)}
    for row in (
        seller.reviews.filter(hidden_at__isnull=True)
        .values("rating")
        .annotate(count=Count("id"))
    ):
        dist[int(row["rating"])] = row["count"]
    total = agg["total"] or 0
    positive = sum(dist[i] for i in (4, 5))
    return {
        "average": float(agg["average"] or 0),
        "total": total,
        "positive_percent": round((positive / total) * 100, 1) if total else 0.0,
        "distribution": dist,
    }


@transaction.atomic
def create_review(*, reviewer, seller, rating, comment, listing=None, request=None):
    if seller.user_id == reviewer.pk:
        raise ValidationError("You cannot review your own seller profile.")
    try:
        rating = int(rating)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"rating": "Rating must be between 1 and 5."}) from exc
    if rating < 1 or rating > 5:
        raise ValidationError({"rating": "Rating must be between 1 and 5."})
    comment = (comment or "").strip()
    if len(comment) < 10:
        raise ValidationError(
            {"comment": "Please write at least 10 characters about your experience."}
        )
    from messaging.models import Conversation

    interaction = Conversation.objects.filter(buyer=reviewer, seller=seller)
    if listing is not None:
        interaction = interaction.filter(listing=listing)
    if not interaction.exists():
        raise ValidationError(
            "You can only review sellers you have interacted with through Marketlift."
        )
    if listing is not None:
        if listing.seller_id != seller.pk:
            raise ValidationError(
                "The selected listing does not belong to this seller."
            )
        if SellerReview.objects.filter(reviewer=reviewer, listing=listing).exists():
            raise ValidationError("You already reviewed this listing.")
    elif SellerReview.objects.filter(
        reviewer=reviewer, seller=seller, listing__isnull=True
    ).exists():
        raise ValidationError("You already reviewed this seller.")
    review = SellerReview.objects.create(
        reviewer=reviewer,
        seller=seller,
        listing=listing,
        rating=rating,
        comment=comment,
    )
    create_notification(
        user=seller.user,
        notification_type="review",
        title="New seller review",
        body=f"{reviewer.full_name or reviewer.email} left a {rating}-star review.",
        href="/selling/reviews",
        data={"reviewId": str(review.id)},
    )
    _refresh_cached_reputation(seller)
    record_audit_event(
        actor=reviewer,
        action="review.created",
        target=review,
        target_type="review",
        target_label=str(seller),
        request=request,
    )
    return review


@transaction.atomic
def reply_to_review(*, seller, review, reply, request=None):
    review = SellerReview.objects.select_for_update().get(pk=review.pk)
    if review.seller_id != seller.pk:
        raise PermissionDenied("You can only reply to reviews on your seller profile.")
    if review.hidden_at:
        raise ValidationError("This review is not visible.")
    if review.seller_reply:
        raise ValidationError("This review already has a seller reply.")
    reply = (reply or "").strip()
    if len(reply) < 2:
        raise ValidationError({"reply": "Reply cannot be empty."})
    review.seller_reply = reply
    review.replied_at = timezone.now()
    review.save(update_fields=("seller_reply", "replied_at", "updated_at"))
    create_notification(
        user=review.reviewer,
        notification_type="review",
        title="Seller replied to your review",
        body=reply[:160],
        href="/account/reviews",
        data={"reviewId": str(review.id)},
    )
    record_audit_event(
        actor=seller.user,
        action="review.replied",
        target=review,
        target_type="review",
        target_label=str(review.seller),
        request=request,
    )
    return review


@transaction.atomic
def delete_own_review(*, reviewer, review, request=None):
    if review.reviewer_id != reviewer.pk:
        raise PermissionDenied("You can only delete your own review.")
    record_audit_event(
        actor=reviewer,
        action="review.deleted",
        target=review,
        target_type="review",
        target_label=str(review.seller),
        metadata={"rating": review.rating},
        request=request,
    )
    seller = review.seller
    review.delete()
    _refresh_cached_reputation(seller)
    return True
