from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event
from notifications.services import create_notification

from .delivery_security import decrypt_delivery_pin, encrypt_delivery_pin
from .models import (
    CommercePayment,
    DeliveryAssignment,
    DeliveryConfirmationAttempt,
    DeliveryRider,
    Order,
    Settlement,
    Shipment,
)


MAX_PIN_ATTEMPTS = 5
PIN_LOCK_MINUTES = 15
ACTIVE_DELIVERY_STATES = {
    Order.Status.AWAITING_SELLER,
    Order.Status.PROCESSING,
    Order.Status.SHIPPED,
    Order.Status.OUT_FOR_DELIVERY,
}


def _request_ip(request) -> str | None:
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (
        forwarded.split(",")[0].strip()
        if forwarded
        else request.META.get("REMOTE_ADDR")
    ) or None


def _latest_payment_is_approved(order: Order) -> bool:
    payment = order.payments.order_by("-created_at").first()
    return bool(payment and payment.status == CommercePayment.Status.APPROVED)


def _assignment_for_shipment(shipment: Shipment) -> DeliveryAssignment:
    assignment, _ = DeliveryAssignment.objects.get_or_create(shipment=shipment)
    return assignment


@transaction.atomic
def secure_local_delivery_pin(order: Order) -> None:
    """Move a freshly generated local-delivery PIN out of the listing snapshot.

    create_checkout_order historically placed the buyer PIN in listing_snapshot so
    it could be returned to the buyer. The outer checkout transaction calls this
    helper before commit, which means plaintext is never committed to PostgreSQL.
    """
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.fulfillment_method != Order.FulfillmentMethod.LOCAL_DELIVERY:
        return
    shipment = Shipment.objects.select_for_update().get(order=order)
    assignment = _assignment_for_shipment(shipment)
    snapshot = dict(order.listing_snapshot or {})
    pin = str(snapshot.pop("delivery_pin", "") or "").strip()
    if pin and shipment.delivered_at is None:
        assignment.delivery_pin_ciphertext = encrypt_delivery_pin(pin)
        assignment.save(update_fields=("delivery_pin_ciphertext", "updated_at"))
    if order.listing_snapshot != snapshot:
        order.listing_snapshot = snapshot
        order.save(update_fields=("listing_snapshot", "updated_at"))


def buyer_delivery_pin(shipment: Shipment) -> str | None:
    if shipment.status == Shipment.Status.DELIVERED or shipment.delivered_at is not None:
        return None
    try:
        assignment = shipment.delivery_assignment
    except DeliveryAssignment.DoesNotExist:
        return None
    return decrypt_delivery_pin(assignment.delivery_pin_ciphertext)


def rider_for_user(user) -> DeliveryRider | None:
    try:
        rider = user.delivery_rider
    except DeliveryRider.DoesNotExist:
        return None
    if not rider.active or not user.is_active or user.suspended_at is not None:
        return None
    return rider


@transaction.atomic
def set_delivery_rider_access(*, user, actor, active: bool, request=None) -> DeliveryRider:
    rider, _ = DeliveryRider.objects.select_for_update().get_or_create(
        user=user,
        defaults={"active": bool(active), "activated_by": actor},
    )
    if active and (not user.is_active or user.suspended_at is not None):
        raise ValidationError("A suspended or inactive account cannot be a delivery rider.")
    if not active:
        has_active_delivery = DeliveryAssignment.objects.filter(
            rider=rider,
            shipment__order__status=Order.Status.OUT_FOR_DELIVERY,
            shipment__status=Shipment.Status.OUT_FOR_DELIVERY,
        ).exists()
        if has_active_delivery:
            raise ValidationError(
                "This rider has an order out for delivery. Reassign or complete it first."
            )
    rider.active = bool(active)
    if active:
        rider.activated_by = actor
    rider.save(update_fields=("active", "activated_by", "updated_at"))
    record_audit_event(
        actor=actor,
        action="delivery.rider_access_updated",
        target=user,
        target_type="user",
        target_label=user.full_name or user.email,
        metadata={"active": rider.active, "rider_id": str(rider.id)},
        request=request,
    )
    return rider


@transaction.atomic
def assign_delivery_rider(*, order: Order, rider: DeliveryRider, actor, request=None) -> Order:
    order = Order.objects.select_for_update().select_related("buyer", "seller__user").get(
        pk=order.pk
    )
    if order.fulfillment_method != Order.FulfillmentMethod.LOCAL_DELIVERY:
        raise ValidationError("Only local-delivery orders can be assigned to a rider.")
    if order.paid_at is None or not _latest_payment_is_approved(order):
        raise ValidationError("Only an approved paid order can be assigned for delivery.")
    if order.status not in {
        Order.Status.AWAITING_SELLER,
        Order.Status.PROCESSING,
        Order.Status.SHIPPED,
    }:
        raise ValidationError("This order is not available for rider assignment.")
    rider = DeliveryRider.objects.select_for_update().select_related("user").get(pk=rider.pk)
    if not rider.active or not rider.user.is_active or rider.user.suspended_at is not None:
        raise ValidationError("The selected rider is not active.")
    shipment = Shipment.objects.select_for_update().get(order=order)
    assignment = _assignment_for_shipment(shipment)
    assignment.rider = rider
    assignment.assigned_by = actor
    assignment.assigned_at = timezone.now()
    assignment.save(
        update_fields=("rider", "assigned_by", "assigned_at", "updated_at")
    )
    record_audit_event(
        actor=actor,
        action="delivery.rider_assigned",
        target=order,
        target_type="commerce_order",
        target_label=order.reference,
        metadata={"rider_id": str(rider.id), "rider_user_id": str(rider.user_id)},
        request=request,
    )
    create_notification(
        user=rider.user,
        notification_type="seller",
        title="New delivery assigned",
        body=f"Order {order.reference} is ready for your delivery queue.",
        href="/delivery",
        data={"orderId": str(order.id), "event": "delivery_assigned"},
    )
    return order


@transaction.atomic
def start_rider_delivery(*, order: Order, rider_user, request=None) -> Order:
    rider = rider_for_user(rider_user)
    if rider is None:
        raise ValidationError("Delivery rider access is not active for this account.")
    order = Order.objects.select_for_update().select_related("buyer", "seller__user").get(
        pk=order.pk
    )
    if order.fulfillment_method != Order.FulfillmentMethod.LOCAL_DELIVERY:
        raise ValidationError("This is not a local-delivery order.")
    if order.paid_at is None or not _latest_payment_is_approved(order):
        raise ValidationError("Only an approved paid order can start delivery.")
    if order.status not in {Order.Status.PROCESSING, Order.Status.SHIPPED}:
        raise ValidationError("This order is not ready to start delivery.")
    shipment = Shipment.objects.select_for_update().get(order=order)
    assignment = DeliveryAssignment.objects.select_for_update().filter(
        shipment=shipment, rider=rider
    ).first()
    if assignment is None:
        raise ValidationError("This delivery is not assigned to your rider account.")
    now = timezone.now()
    order.status = Order.Status.OUT_FOR_DELIVERY
    order.save(update_fields=("status", "updated_at"))
    shipment.status = Shipment.Status.OUT_FOR_DELIVERY
    shipment.save(update_fields=("status", "updated_at"))
    record_audit_event(
        actor=rider_user,
        action="delivery.started",
        target=order,
        target_type="commerce_order",
        target_label=order.reference,
        metadata={"rider_id": str(rider.id), "started_at": now.isoformat()},
        request=request,
    )
    create_notification(
        user=order.buyer,
        notification_type="seller",
        title="Your order is out for delivery",
        body=f"Order {order.reference} is on the way. Share your delivery PIN only after handoff.",
        href="/account/orders",
        data={"orderId": str(order.id), "event": "out_for_delivery"},
    )
    create_notification(
        user=order.seller.user,
        notification_type="seller",
        title="Order is out for delivery",
        body=f"Order {order.reference} is now with the assigned rider.",
        href="/selling/orders",
        data={"orderId": str(order.id), "event": "out_for_delivery"},
    )
    return order


def _complete_delivery_locked(
    *,
    order: Order,
    shipment: Shipment,
    assignment: DeliveryAssignment,
    actor,
    source: str,
    request=None,
    admin_reason: str = "",
) -> Order:
    now = timezone.now()
    shipment.status = Shipment.Status.DELIVERED
    shipment.delivered_at = now
    shipment.delivery_pin_hash = ""
    shipment.proof = {
        "confirmation_source": source,
        "actor_user_id": str(actor.id) if actor else "",
        "confirmed_at": now.isoformat(),
    }
    shipment.save(
        update_fields=(
            "status",
            "delivered_at",
            "delivery_pin_hash",
            "proof",
            "updated_at",
        )
    )
    assignment.delivered_by = actor
    assignment.confirmation_source = source
    assignment.admin_override_reason = admin_reason
    assignment.delivery_pin_ciphertext = ""
    assignment.delivery_pin_failure_count = 0
    assignment.delivery_pin_locked_until = None
    assignment.save(
        update_fields=(
            "delivered_by",
            "confirmation_source",
            "admin_override_reason",
            "delivery_pin_ciphertext",
            "delivery_pin_failure_count",
            "delivery_pin_locked_until",
            "updated_at",
        )
    )
    DeliveryConfirmationAttempt.objects.create(
        assignment=assignment,
        actor=actor,
        source=source,
        success=True,
        reason="confirmed",
        ip_address=_request_ip(request),
    )
    order.status = Order.Status.DELIVERED
    order.delivered_at = now
    order.save(update_fields=("status", "delivered_at", "updated_at"))
    settlement = Settlement.objects.select_for_update().get(order=order)
    hours = int(getattr(settings, "MARKETLIFT_BUYER_PROTECTION_HOURS", 48))
    settlement.status = Settlement.Status.HELD
    settlement.release_after = now + timedelta(hours=hours)
    settlement.save(update_fields=("status", "release_after", "updated_at"))
    create_notification(
        user=order.buyer,
        notification_type="seller",
        title="Delivery confirmed",
        body=f"Order {order.reference} was delivered. Report a problem during the buyer-protection period if needed.",
        href="/account/orders",
        data={"orderId": str(order.id), "event": "delivered"},
    )
    create_notification(
        user=order.seller.user,
        notification_type="seller",
        title="Your order was delivered",
        body=f"Order {order.reference} was delivered successfully. Seller proceeds remain held during buyer protection.",
        href="/selling/orders",
        data={"orderId": str(order.id), "event": "delivered"},
    )
    return order


def confirm_rider_delivery_pin(*, order: Order, rider_user, delivery_pin: str, request=None) -> Order:
    failure: ValidationError | None = None
    completed_order: Order | None = None
    with transaction.atomic():
        rider = rider_for_user(rider_user)
        if rider is None:
            raise ValidationError("Delivery rider access is not active for this account.")
        order = Order.objects.select_for_update().select_related("buyer", "seller__user").get(
            pk=order.pk
        )
        if order.fulfillment_method != Order.FulfillmentMethod.LOCAL_DELIVERY:
            raise ValidationError("This is not a local-delivery order.")
        shipment = Shipment.objects.select_for_update().get(order=order)
        assignment = DeliveryAssignment.objects.select_for_update().filter(
            shipment=shipment, rider=rider
        ).first()
        if assignment is None:
            raise ValidationError("This delivery is not assigned to your rider account.")
        if order.status == Order.Status.DELIVERED and shipment.status == Shipment.Status.DELIVERED:
            return order
        if order.status != Order.Status.OUT_FOR_DELIVERY or shipment.status != Shipment.Status.OUT_FOR_DELIVERY:
            raise ValidationError("This order is not currently out for delivery.")
        if order.paid_at is None or not _latest_payment_is_approved(order):
            raise ValidationError("Delivery cannot be confirmed for an unpaid order.")

        now = timezone.now()
        if assignment.delivery_pin_locked_until and assignment.delivery_pin_locked_until > now:
            DeliveryConfirmationAttempt.objects.create(
                assignment=assignment,
                actor=rider_user,
                source=DeliveryAssignment.ConfirmationSource.RIDER_PIN,
                success=False,
                reason="temporarily_locked",
                ip_address=_request_ip(request),
            )
            failure = ValidationError(
                {"deliveryPin": "Too many incorrect attempts. Try again later."}
            )
        else:
            candidate = str(delivery_pin or "").strip()
            valid = (
                len(candidate) == 6
                and candidate.isdigit()
                and bool(shipment.delivery_pin_hash)
                and check_password(candidate, shipment.delivery_pin_hash)
            )
            if not valid:
                assignment.delivery_pin_failure_count += 1
                if assignment.delivery_pin_failure_count >= MAX_PIN_ATTEMPTS:
                    assignment.delivery_pin_locked_until = now + timedelta(
                        minutes=PIN_LOCK_MINUTES
                    )
                assignment.save(
                    update_fields=(
                        "delivery_pin_failure_count",
                        "delivery_pin_locked_until",
                        "updated_at",
                    )
                )
                DeliveryConfirmationAttempt.objects.create(
                    assignment=assignment,
                    actor=rider_user,
                    source=DeliveryAssignment.ConfirmationSource.RIDER_PIN,
                    success=False,
                    reason="invalid_pin",
                    ip_address=_request_ip(request),
                )
                failure = ValidationError(
                    {
                        "deliveryPin": (
                            "Too many incorrect attempts. Try again later."
                            if assignment.delivery_pin_locked_until
                            else "Invalid delivery code."
                        )
                    }
                )
            else:
                completed_order = _complete_delivery_locked(
                    order=order,
                    shipment=shipment,
                    assignment=assignment,
                    actor=rider_user,
                    source=DeliveryAssignment.ConfirmationSource.RIDER_PIN,
                    request=request,
                )
                record_audit_event(
                    actor=rider_user,
                    action="delivery.confirmed_by_rider",
                    target=order,
                    target_type="commerce_order",
                    target_label=order.reference,
                    metadata={"rider_id": str(rider.id)},
                    request=request,
                )
    if failure is not None:
        raise failure
    if completed_order is None:
        raise ValidationError("Delivery could not be confirmed.")
    return completed_order


@transaction.atomic
def admin_override_delivery(*, order: Order, actor, reason: str, request=None) -> Order:
    reason = str(reason or "").strip()
    if len(reason) < 10:
        raise ValidationError({"reason": "Provide a clear override reason of at least 10 characters."})
    order = Order.objects.select_for_update().select_related("buyer", "seller__user").get(
        pk=order.pk
    )
    if order.fulfillment_method != Order.FulfillmentMethod.LOCAL_DELIVERY:
        raise ValidationError("Only local deliveries can use a delivery override.")
    if order.status == Order.Status.DELIVERED:
        return order
    if order.status not in ACTIVE_DELIVERY_STATES:
        raise ValidationError("This order cannot be overridden as delivered in its current state.")
    if order.paid_at is None or not _latest_payment_is_approved(order):
        raise ValidationError("An unpaid order cannot be overridden as delivered.")
    shipment = Shipment.objects.select_for_update().get(order=order)
    assignment = _assignment_for_shipment(shipment)
    order = _complete_delivery_locked(
        order=order,
        shipment=shipment,
        assignment=assignment,
        actor=actor,
        source=DeliveryAssignment.ConfirmationSource.ADMIN_OVERRIDE,
        request=request,
        admin_reason=reason,
    )
    record_audit_event(
        actor=actor,
        action="delivery.admin_override",
        target=order,
        target_type="commerce_order",
        target_label=order.reference,
        metadata={"reason": reason},
        request=request,
    )
    return order
