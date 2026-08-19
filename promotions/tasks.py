from celery import shared_task
from django.utils import timezone

from notifications.services import create_notification

from .models import ListingPromotion


@shared_task
def notify_expired_promotions():
    now = timezone.now()
    rows = list(
        ListingPromotion.objects.filter(
            cancelled_at__isnull=True,
            ends_at__lte=now,
            expiry_notified_at__isnull=True,
        ).select_related("listing__seller__user", "product")[:500]
    )
    for promotion in rows:
        create_notification(
            user=promotion.listing.seller.user,
            notification_type="promotion",
            title="Promotion ended",
            body=f"{promotion.product.name} has ended for {promotion.listing.title}.",
            href="/selling/listings",
            data={
                "listingId": str(promotion.listing_id),
                "promotionId": str(promotion.id),
            },
        )
        promotion.expiry_notified_at = now
        promotion.save(update_fields=("expiry_notified_at", "updated_at"))
    return len(rows)
