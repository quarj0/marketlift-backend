import strawberry
from django.core.exceptions import ValidationError

from accounts.models import User
from marketlift.graphql.auth import request_from_info, require_staff, require_user
from marketlift.graphql.errors import not_found_error, validation_error

from commerce.delivery_services import (
    admin_override_delivery,
    assign_delivery_rider,
    confirm_rider_delivery_pin,
    set_delivery_rider_access,
    start_rider_delivery,
)
from commerce.models import DeliveryAssignment, DeliveryRider, Order, Shipment

from .mappers import order_to_type, rider_admin_to_type
from .types import DeliveryRiderAdminType, OrderType


ASSIGNABLE_DELIVERY_STATES = {
    Order.Status.PROCESSING,
    Order.Status.SHIPPED,
}


def _order(order_id) -> Order:
    try:
        return Order.objects.get(pk=str(order_id))
    except (Order.DoesNotExist, ValueError) as exc:
        raise not_found_error("Order", code="ORDER_NOT_FOUND") from exc


def _response_order(order_id) -> Order:
    return (
        Order.objects.select_related(
            "buyer",
            "seller",
            "seller__user",
            "listing",
            "shipment",
            "shipment__delivery_assignment",
            "shipment__delivery_assignment__rider",
            "shipment__delivery_assignment__rider__user",
        )
        .prefetch_related("payments")
        .get(pk=order_id)
    )


def _require_assignable_order(order: Order) -> None:
    if order.fulfillment_method != Order.FulfillmentMethod.LOCAL_DELIVERY:
        raise ValidationError("Only local-delivery orders can be assigned to riders.")
    if order.status not in ASSIGNABLE_DELIVERY_STATES:
        raise ValidationError(
            "A rider can be assigned only after the seller is processing or has prepared the order."
        )


def _require_override_ready(order: Order) -> None:
    if order.fulfillment_method != Order.FulfillmentMethod.LOCAL_DELIVERY:
        raise ValidationError("Only local deliveries can use a delivery override.")
    if order.status != Order.Status.OUT_FOR_DELIVERY:
        raise ValidationError(
            "Administrator delivery override is available only after an assigned rider has started delivery."
        )
    ready = DeliveryAssignment.objects.filter(
        shipment__order=order,
        shipment__status=Shipment.Status.OUT_FOR_DELIVERY,
        rider__isnull=False,
    ).exists()
    if not ready:
        raise ValidationError(
            "Administrator delivery override requires an active rider assignment already out for delivery."
        )


@strawberry.type
class DeliveryMutation:
    @strawberry.mutation
    def set_delivery_rider(
        self,
        info: strawberry.Info,
        email: str,
        active: bool = True,
    ) -> DeliveryRiderAdminType:
        actor = require_staff(info, roles={User.AdminRole.ADMIN})
        try:
            user = User.objects.get(email__iexact=str(email or "").strip())
        except User.DoesNotExist as exc:
            raise not_found_error("User", code="USER_NOT_FOUND") from exc
        try:
            rider = set_delivery_rider_access(
                user=user,
                actor=actor,
                active=active,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(
                exc, code="DELIVERY_RIDER_INVALID", status=409
            ) from exc
        rider = DeliveryRider.objects.select_related("user").get(pk=rider.pk)
        return rider_admin_to_type(rider)

    @strawberry.mutation
    def assign_commerce_delivery_rider(
        self,
        info: strawberry.Info,
        order_id: strawberry.ID,
        rider_id: strawberry.ID,
    ) -> OrderType:
        actor = require_staff(info, roles={User.AdminRole.ADMIN})
        try:
            rider = DeliveryRider.objects.select_related("user").get(pk=str(rider_id))
        except (DeliveryRider.DoesNotExist, ValueError) as exc:
            raise not_found_error(
                "Delivery rider", code="DELIVERY_RIDER_NOT_FOUND"
            ) from exc
        try:
            order = _order(order_id)
            _require_assignable_order(order)
            order = assign_delivery_rider(
                order=order,
                rider=rider,
                actor=actor,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(
                exc, code="DELIVERY_ASSIGNMENT_INVALID", status=409
            ) from exc
        return order_to_type(_response_order(order.pk), buyer_view=False)

    @strawberry.mutation
    def start_commerce_delivery(
        self,
        info: strawberry.Info,
        order_id: strawberry.ID,
    ) -> OrderType:
        user = require_user(info)
        try:
            order = start_rider_delivery(
                order=_order(order_id),
                rider_user=user,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(
                exc, code="DELIVERY_START_INVALID", status=409
            ) from exc
        return order_to_type(
            _response_order(order.pk),
            buyer_view=False,
            include_shipping_address=True,
        )

    @strawberry.mutation
    def confirm_commerce_rider_delivery_pin(
        self,
        info: strawberry.Info,
        order_id: strawberry.ID,
        delivery_pin: str,
    ) -> OrderType:
        user = require_user(info)
        try:
            order = confirm_rider_delivery_pin(
                order=_order(order_id),
                rider_user=user,
                delivery_pin=delivery_pin,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(
                exc, code="DELIVERY_PIN_INVALID", status=409
            ) from exc
        return order_to_type(_response_order(order.pk), buyer_view=False)

    @strawberry.mutation
    def admin_override_commerce_delivery(
        self,
        info: strawberry.Info,
        order_id: strawberry.ID,
        reason: str,
    ) -> OrderType:
        actor = require_staff(info, roles={User.AdminRole.ADMIN})
        try:
            order = _order(order_id)
            _require_override_ready(order)
            order = admin_override_delivery(
                order=order,
                actor=actor,
                reason=reason,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(
                exc, code="DELIVERY_OVERRIDE_INVALID", status=409
            ) from exc
        return order_to_type(_response_order(order.pk), buyer_view=False)
