from datetime import timedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from notifications.services import create_notification
from .models import SellerPlan, SellerSubscription


def expire_due_subscriptions(*, seller=None):
    now = timezone.now()
    qs = SellerSubscription.objects.filter(
        status=SellerSubscription.Status.ACTIVE,
        current_period_end__isnull=False,
        current_period_end__lte=now,
    )
    if seller is not None:
        qs = qs.filter(seller=seller)
    return qs.update(status=SellerSubscription.Status.EXPIRED)


def get_active_subscription(seller):
    expire_due_subscriptions(seller=seller)
    return (
        SellerSubscription.objects.select_related("plan", "seller", "seller__user")
        .filter(
            seller=seller, status=SellerSubscription.Status.ACTIVE, plan__active=True
        )
        .first()
    )


def get_effective_plan(seller):
    subscription = get_active_subscription(seller)
    if subscription:
        return subscription.plan
    return SellerPlan.objects.filter(code="free", active=True).first()


@transaction.atomic
def activate_paid_subscription(
    *, seller, plan, billing_cycle: str, actor=None, request=None
):
    if plan.code == "free":
        raise ValidationError(
            "Free is the fallback plan and does not create a paid subscription."
        )
    if billing_cycle not in SellerSubscription.BillingCycle.values:
        raise ValidationError("Invalid billing cycle.")
    now = timezone.now()
    existing = get_active_subscription(seller)
    if existing:
        existing.status = SellerSubscription.Status.CANCELLED
        existing.cancelled_at = now
        existing.save(update_fields=("status", "cancelled_at", "updated_at"))
    days = 365 if billing_cycle == SellerSubscription.BillingCycle.YEARLY else 30
    subscription = SellerSubscription.objects.create(
        seller=seller,
        plan=plan,
        billing_cycle=billing_cycle,
        status=SellerSubscription.Status.ACTIVE,
        current_period_start=now,
        current_period_end=now + timedelta(days=days),
        promotion_credits_remaining=plan.promotion_credits,
    )
    record_audit_event(
        actor=actor,
        action="subscription.activated",
        target=subscription,
        target_type="subscription",
        target_label=f"{seller} · {plan.name}",
        metadata={"plan": plan.code, "billing_cycle": billing_cycle},
        request=request,
    )
    create_notification(
        user=seller.user,
        notification_type="subscription",
        title=f"{plan.name} plan activated",
        body="Your Marketlift seller plan is now active.",
        href="/selling/plan",
    )
    return subscription


@transaction.atomic
def cancel_subscription(*, seller, actor=None, at_period_end=True, request=None):
    subscription = get_active_subscription(seller)
    if not subscription:
        raise ValidationError("There is no paid subscription to cancel.")
    now = timezone.now()
    if at_period_end:
        subscription.cancel_at_period_end = True
    else:
        subscription.status = SellerSubscription.Status.CANCELLED
        subscription.cancelled_at = now
    subscription.save()
    record_audit_event(
        actor=actor,
        action=(
            "subscription.cancel_requested"
            if at_period_end
            else "subscription.cancelled"
        ),
        target=subscription,
        target_type="subscription",
        target_label=f"{seller} · {subscription.plan.name}",
        metadata={"at_period_end": at_period_end},
        request=request,
    )
    create_notification(
        user=seller.user,
        notification_type="subscription",
        title=(
            "Subscription cancellation scheduled"
            if at_period_end
            else "Subscription cancelled"
        ),
        body=(
            "Your paid seller plan will end at the close of the current billing period."
            if at_period_end
            else "Your account now uses the Free seller plan limits."
        ),
        href="/selling/plan",
    )
    return subscription


def _decimal_amount(value):
    from decimal import Decimal, InvalidOperation

    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError("Enter a valid price.") from exc


@transaction.atomic
def create_seller_plan(
    *,
    code: str,
    name: str,
    monthly_price,
    yearly_price,
    listing_limit: int,
    promotion_credits: int = 0,
    visibility_weight=1,
    recommended: bool = False,
    features=None,
    active: bool = True,
    actor=None,
    request=None,
):
    from django.utils.text import slugify

    code = slugify((code or name or "").strip())
    name = (name or "").strip()
    if not code or not name:
        raise ValidationError("Plan code and name are required.")
    if SellerPlan.objects.filter(code=code).exists():
        raise ValidationError({"code": "A seller plan with this code already exists."})
    plan = SellerPlan(
        code=code,
        name=name,
        monthly_price=_decimal_amount(monthly_price),
        yearly_price=_decimal_amount(yearly_price),
        listing_limit=listing_limit,
        promotion_credits=promotion_credits,
        visibility_weight=_decimal_amount(visibility_weight),
        recommended=recommended,
        features=list(features or []),
        active=active,
        sort_order=(
            SellerPlan.objects.order_by("-sort_order")
            .values_list("sort_order", flat=True)
            .first()
            or 0
        )
        + 10,
    )
    plan.full_clean()
    plan.save()
    record_audit_event(
        actor=actor,
        action="seller_plan.created",
        target=plan,
        target_type="seller_plan",
        target_label=plan.name,
        metadata={"code": plan.code},
        request=request,
    )
    return plan


@transaction.atomic
def update_seller_plan(
    *,
    plan,
    name: str,
    monthly_price,
    yearly_price,
    listing_limit: int,
    promotion_credits: int,
    visibility_weight,
    recommended: bool,
    features,
    active: bool = True,
    actor=None,
    request=None,
):
    if plan.code == "free" and not active:
        raise ValidationError("The Free fallback plan cannot be disabled.")
    plan.name = (name or "").strip()
    if not plan.name:
        raise ValidationError({"name": "Plan name is required."})
    plan.monthly_price = _decimal_amount(monthly_price)
    plan.yearly_price = _decimal_amount(yearly_price)
    plan.listing_limit = listing_limit
    plan.promotion_credits = promotion_credits
    plan.visibility_weight = _decimal_amount(visibility_weight)
    plan.recommended = recommended
    plan.features = list(features or [])
    plan.active = active
    plan.full_clean()
    plan.save()
    record_audit_event(
        actor=actor,
        action="seller_plan.updated",
        target=plan,
        target_type="seller_plan",
        target_label=plan.name,
        metadata={"code": plan.code, "active": plan.active},
        request=request,
    )
    return plan
