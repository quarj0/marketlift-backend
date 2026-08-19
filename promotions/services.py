from datetime import timedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from audit.services import record_audit_event
from notifications.services import create_notification
from subscriptions.services import get_active_subscription
from .models import ListingPromotion


@transaction.atomic
def activate_with_plan_credit(*, seller, listing, product, request=None):
    if listing.seller_id != seller.id:
        raise ValidationError("You can only promote your own listing.")
    if listing.status != listing.Status.PUBLISHED:
        raise ValidationError("Only published listings can be promoted.")
    if not product.active:
        raise ValidationError("This promotion is unavailable.")
    subscription = get_active_subscription(seller)
    if not subscription or subscription.promotion_credits_remaining < 1:
        raise ValidationError("Your current plan has no promotion credits remaining.")
    subscription.promotion_credits_remaining -= 1
    subscription.save(update_fields=("promotion_credits_remaining", "updated_at"))
    item = ListingPromotion.objects.create(
        listing=listing,
        product=product,
        source=ListingPromotion.Source.PLAN_CREDIT,
        starts_at=timezone.now(),
        ends_at=timezone.now() + timedelta(days=product.duration_days),
    )
    record_audit_event(
        actor=seller.user,
        action="promotion.credit_used",
        target=item,
        target_type="promotion",
        target_label=f"{listing.title} · {product.name}",
        metadata={
            "subscription_id": str(subscription.id),
            "credits_remaining": subscription.promotion_credits_remaining,
        },
        request=request,
    )
    create_notification(
        user=seller.user,
        notification_type="promotion",
        title="Promotion activated",
        body=f"{product.name} is active for {listing.title}. You have {subscription.promotion_credits_remaining} plan credits remaining.",
        href="/selling/listings",
    )
    return item
