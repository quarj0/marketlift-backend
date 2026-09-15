import strawberry
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from strawberry.scalars import JSON

from accounts.models import User
from categories.models import Category
from listings.models import Listing
from marketlift.graphql.auth import (
    request_from_info,
    require_seller,
    require_staff,
    require_user,
)
from marketlift.graphql.errors import domain_error, not_found_error, validation_error

from commerce.delivery_guards import buyer_confirm_non_local_delivery
from commerce.models import CommercePayment, Dispute, Order, Settlement
from commerce.providers.base import CommerceProviderError
from commerce.services import (
    activate_seller_payments,
    configure_listing_commerce,
    create_checkout_order,
    mark_order_processing,
    mark_order_shipped,
    open_order_dispute,
    refund_order,
    set_category_commerce_policy,
    withdraw_available_balance,
)

from .mappers import (
    category_policy_to_type,
    dispute_to_type,
    order_to_type,
    payment_account_to_type,
    payment_to_type,
)
from .types import (
    CategoryCommercePolicyType,
    CheckoutPayload,
    DisputeType,
    OrderType,
    PayoutPayload,
    SellerPaymentAccountType,
)


def _provider_error(exc: CommerceProviderError):
    return domain_error(str(exc), code="PAYMENT_PROVIDER_ERROR", status=502)


def _owned_listing(seller, listing_id) -> Listing:
    try:
        return Listing.objects.select_related("category", "seller").get(
            pk=str(listing_id), seller=seller
        )
    except (Listing.DoesNotExist, ValueError) as exc:
        raise not_found_error("Listing", code="LISTING_NOT_FOUND") from exc


def _order_for_buyer(user, order_id) -> Order:
    try:
        return Order.objects.select_related("buyer", "seller", "listing").get(
            pk=str(order_id), buyer=user
        )
    except (Order.DoesNotExist, ValueError) as exc:
        raise not_found_error("Order", code="ORDER_NOT_FOUND") from exc


def _order_for_seller(seller, order_id) -> Order:
    try:
        return Order.objects.select_related("buyer", "seller", "listing").get(
            pk=str(order_id), seller=seller
        )
    except (Order.DoesNotExist, ValueError) as exc:
        raise not_found_error("Order", code="ORDER_NOT_FOUND") from exc


@strawberry.type
class CommerceMutation:
    @strawberry.mutation
    def configure_listing_commerce(
        self,
        info: strawberry.Info,
        listing_id: strawberry.ID,
        checkout_enabled: bool,
        stock_quantity: int = 1,
        shipping_enabled: bool = False,
        local_delivery_enabled: bool = False,
        pickup_enabled: bool = True,
        package_weight_grams: int | None = None,
        package_length_cm: int | None = None,
        package_width_cm: int | None = None,
        package_height_cm: int | None = None,
    ) -> bool:
        seller = require_seller(info)
        listing = _owned_listing(seller, listing_id)
        try:
            configure_listing_commerce(
                listing=listing,
                checkout_enabled=checkout_enabled,
                stock_quantity=stock_quantity,
                shipping_enabled=shipping_enabled,
                local_delivery_enabled=local_delivery_enabled,
                pickup_enabled=pickup_enabled,
                package_weight_grams=package_weight_grams,
                package_length_cm=package_length_cm,
                package_width_cm=package_width_cm,
                package_height_cm=package_height_cm,
            )
        except ValidationError as exc:
            raise validation_error(
                exc, code="COMMERCE_LISTING_VALIDATION_ERROR"
            ) from exc
        return True

    @strawberry.mutation
    def activate_seller_payments(
        self,
        info: strawberry.Info,
        recipient: JSON,
        payout_method: str,
    ) -> SellerPaymentAccountType:
        seller = require_seller(info)
        try:
            account = activate_seller_payments(
                seller=seller,
                recipient_payload=dict(recipient or {}),
                payout_method=payout_method,
            )
        except ValidationError as exc:
            raise validation_error(
                exc, code="SELLER_PAYMENT_VALIDATION_ERROR"
            ) from exc
        except CommerceProviderError as exc:
            raise _provider_error(exc) from exc
        return payment_account_to_type(account)

    @strawberry.mutation
    def create_commerce_checkout(
        self,
        info: strawberry.Info,
        listing_id: strawberry.ID,
        fulfillment_method: str,
        payment_method: str,
        customer_document: str,
        customer_phone: str,
        idempotency_key: str,
        quantity: int = 1,
        shipping_address: JSON | None = None,
        card_id: str | None = None,
    ) -> CheckoutPayload:
        buyer = require_user(info)
        try:
            order, payment = create_checkout_order(
                buyer=buyer,
                listing_id=listing_id,
                quantity=quantity,
                fulfillment_method=fulfillment_method,
                shipping_address=dict(shipping_address or {}),
                payment_method=payment_method,
                customer_document=customer_document,
                customer_phone=customer_phone,
                card_id=card_id,
                idempotency_key=idempotency_key,
            )
        except ValidationError as exc:
            raise validation_error(exc, code="CHECKOUT_VALIDATION_ERROR") from exc
        except CommerceProviderError as exc:
            raise _provider_error(exc) from exc
        order = Order.objects.select_related("buyer", "seller", "listing").get(
            pk=order.pk
        )
        return CheckoutPayload(
            order=order_to_type(order, buyer_view=True),
            payment=payment_to_type(payment),
        )

    @strawberry.mutation
    def mark_commerce_order_processing(
        self, info: strawberry.Info, order_id: strawberry.ID
    ) -> OrderType:
        seller = require_seller(info)
        try:
            order = mark_order_processing(
                order=_order_for_seller(seller, order_id), seller=seller
            )
        except ValidationError as exc:
            raise validation_error(
                exc, code="ORDER_TRANSITION_INVALID", status=409
            ) from exc
        return order_to_type(
            order, buyer_view=False, include_shipping_address=True
        )

    @strawberry.mutation
    def mark_commerce_order_shipped(
        self,
        info: strawberry.Info,
        order_id: strawberry.ID,
        carrier: str = "",
        tracking_code: str = "",
    ) -> OrderType:
        seller = require_seller(info)
        try:
            order = mark_order_shipped(
                order=_order_for_seller(seller, order_id),
                seller=seller,
                carrier=carrier,
                tracking_code=tracking_code,
            )
        except ValidationError as exc:
            raise validation_error(
                exc, code="ORDER_TRANSITION_INVALID", status=409
            ) from exc
        return order_to_type(
            order, buyer_view=False, include_shipping_address=True
        )

    @strawberry.mutation
    def confirm_commerce_order_received(
        self, info: strawberry.Info, order_id: strawberry.ID
    ) -> OrderType:
        user = require_user(info)
        try:
            order = buyer_confirm_non_local_delivery(
                order=_order_for_buyer(user, order_id),
                buyer=user,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(
                exc, code="ORDER_DELIVERY_INVALID", status=409
            ) from exc
        return order_to_type(order, buyer_view=True)

    @strawberry.mutation
    def open_commerce_dispute(
        self,
        info: strawberry.Info,
        order_id: strawberry.ID,
        reason: str,
        description: str = "",
    ) -> DisputeType:
        user = require_user(info)
        try:
            order = Order.objects.get(pk=str(order_id))
        except (Order.DoesNotExist, ValueError) as exc:
            raise not_found_error("Order", code="ORDER_NOT_FOUND") from exc
        try:
            dispute = open_order_dispute(
                order=order, user=user, reason=reason, description=description
            )
        except ValidationError as exc:
            raise validation_error(
                exc, code="DISPUTE_VALIDATION_ERROR", status=409
            ) from exc
        return dispute_to_type(dispute)

    @strawberry.mutation
    def withdraw_seller_balance(self, info: strawberry.Info) -> PayoutPayload:
        seller = require_seller(info)
        try:
            payload = withdraw_available_balance(seller=seller)
        except ValidationError as exc:
            raise validation_error(
                exc, code="PAYOUT_VALIDATION_ERROR", status=409
            ) from exc
        except CommerceProviderError as exc:
            raise _provider_error(exc) from exc
        return PayoutPayload(**payload)

    @strawberry.mutation
    def set_category_commerce_policy(
        self,
        info: strawberry.Info,
        category_id: str,
        mode: str,
        requires_verified_seller: bool = True,
        max_checkout_value_cents: int | None = None,
        shipping_allowed: bool = False,
        local_delivery_allowed: bool = False,
        pickup_allowed: bool = True,
    ) -> CategoryCommercePolicyType:
        require_staff(info, roles={User.AdminRole.ADMIN})
        try:
            category = Category.objects.get(slug=category_id)
        except Category.DoesNotExist as exc:
            raise not_found_error("Category", code="CATEGORY_NOT_FOUND") from exc
        try:
            policy = set_category_commerce_policy(
                category=category,
                mode=mode,
                requires_verified_seller=requires_verified_seller,
                max_checkout_value_cents=max_checkout_value_cents,
                shipping_allowed=shipping_allowed,
                local_delivery_allowed=local_delivery_allowed,
                pickup_allowed=pickup_allowed,
            )
        except ValidationError as exc:
            raise validation_error(
                exc, code="CATEGORY_COMMERCE_VALIDATION_ERROR"
            ) from exc
        return category_policy_to_type(category, policy)

    @strawberry.mutation
    def resolve_commerce_dispute(
        self,
        info: strawberry.Info,
        dispute_id: strawberry.ID,
        resolution: str,
    ) -> DisputeType:
        require_staff(
            info,
            roles={User.AdminRole.ADMIN, User.AdminRole.FINANCE},
        )
        try:
            with transaction.atomic():
                dispute = (
                    Dispute.objects.select_for_update()
                    .select_related("order")
                    .get(pk=str(dispute_id))
                )
                if dispute.status != Dispute.Status.OPEN:
                    raise domain_error(
                        "This dispute is already final.",
                        code="DISPUTE_FINAL",
                        status=409,
                    )
                order = Order.objects.select_for_update().get(
                    pk=dispute.order_id
                )

                if resolution == "buyer":
                    refund_order(
                        order=order,
                        reason="Admin dispute resolution",
                    )
                    dispute.status = Dispute.Status.RESOLVED_BUYER
                elif resolution == "seller":
                    payment = (
                        order.payments.select_for_update()
                        .order_by("-created_at")
                        .first()
                    )
                    if not payment or payment.status != CommercePayment.Status.APPROVED:
                        raise ValidationError(
                            "Seller proceeds can only be released for an approved payment."
                        )
                    settlement = Settlement.objects.select_for_update().get(
                        order=order
                    )
                    if settlement.status != Settlement.Status.BLOCKED:
                        raise ValidationError(
                            "Only a blocked disputed settlement can be released."
                        )
                    settlement.status = Settlement.Status.AVAILABLE
                    settlement.release_after = timezone.now()
                    settlement.save(
                        update_fields=(
                            "status",
                            "release_after",
                            "updated_at",
                        )
                    )
                    order.status = Order.Status.COMPLETED
                    order.completed_at = timezone.now()
                    order.save(
                        update_fields=(
                            "status",
                            "completed_at",
                            "updated_at",
                        )
                    )
                    dispute.status = Dispute.Status.RESOLVED_SELLER
                else:
                    raise ValidationError(
                        {"resolution": "Use 'buyer' or 'seller'."}
                    )

                dispute.resolved_at = timezone.now()
                dispute.save(
                    update_fields=("status", "resolved_at", "updated_at")
                )
        except (Dispute.DoesNotExist, ValueError) as exc:
            raise not_found_error("Dispute", code="DISPUTE_NOT_FOUND") from exc
        except ValidationError as exc:
            raise validation_error(
                exc, code="DISPUTE_RESOLUTION_INVALID"
            ) from exc
        except CommerceProviderError as exc:
            raise _provider_error(exc) from exc
        return dispute_to_type(dispute)
