from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from notifications.services import create_notification
from platform_settings.services import get_platform_configuration

from .models import Listing


@shared_task
def expire_due_listings():
    """Expire due listings and renew eligible seller listings atomically."""
    now = timezone.now()
    config = get_platform_configuration()
    fallback_cutoff = now - timedelta(days=config.default_listing_duration_days)

    due_ids = list(
        Listing.objects.filter(status=Listing.Status.PUBLISHED)
        .filter(
            # `expires_at` is authoritative for new publications. The fallback
            # keeps pre-migration/imported records from living forever.
            models_q_expires(now, fallback_cutoff)
        )
        .values_list("id", flat=True)[:1000]
    )

    expired = 0
    renewed = 0
    for listing_id in due_ids:
        with transaction.atomic():
            locked = Listing.objects.select_for_update().only("pk").get(pk=listing_id)
            listing = Listing.objects.select_related("seller__user", "category").get(
                pk=locked.pk
            )
            if listing.status != Listing.Status.PUBLISHED:
                continue

            settings_obj = getattr(listing.seller, "settings", None)
            can_renew = (
                settings_obj is not None
                and settings_obj.auto_renew
                and not listing.seller.is_suspended
                and listing.category_id is not None
                and listing.category.active
                and (
                    not settings.MARKETLIFT_IDENTITY_VERIFICATION_ENABLED
                    or not config.seller_verification_required
                    or listing.seller.verified
                )
            )

            if can_renew:
                listing.published_at = now
                listing.expires_at = now + timedelta(
                    days=config.default_listing_duration_days
                )
                listing.expired_at = None
                listing.save(
                    update_fields=(
                        "published_at",
                        "expires_at",
                        "expired_at",
                        "updated_at",
                    )
                )
                renewed += 1
                if settings_obj.listing_status:
                    create_notification(
                        user=listing.seller.user,
                        notification_type="listing",
                        title="Listing renewed",
                        body=f"{listing.title} was renewed automatically.",
                        href="/selling/listings",
                        data={"listingId": str(listing.id)},
                    )
                continue

            listing.status = Listing.Status.EXPIRED
            listing.expired_at = now
            listing.save(update_fields=("status", "expired_at", "updated_at"))
            expired += 1
            if settings_obj is None or settings_obj.listing_status:
                create_notification(
                    user=listing.seller.user,
                    notification_type="listing",
                    title="Listing expired",
                    body=f"{listing.title} has expired.",
                    href="/selling/listings",
                    data={"listingId": str(listing.id)},
                )

    return {"expired": expired, "renewed": renewed}


def models_q_expires(now, fallback_cutoff):
    from django.db.models import Q

    return Q(expires_at__lte=now) | Q(
        expires_at__isnull=True, published_at__lte=fallback_cutoff
    )
