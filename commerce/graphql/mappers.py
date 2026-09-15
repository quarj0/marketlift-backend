from commerce.delivery_services import buyer_delivery_pin

from .types import (
    CategoryCommercePolicyType,
    CommercePaymentType,
    DeliveryRiderAdminType,
    DeliveryRiderSummaryType,
    DisputeType,
    ListingCommerceType,
    OrderType,
    SellerPaymentAccountType,
    SellerWalletType,
    SettlementType,
    ShipmentType,
)


def listing_commerce_to_type(state: dict) -> ListingCommerceType:
    return ListingCommerceType(
        mode=state["mode"],
        checkout_enabled=state["checkout_enabled"],
        inspection_allowed=state["inspection_allowed"],
        stock_quantity=state["stock_quantity"],
        fulfillment_methods=state["fulfillment_methods"],
        reasons=state["reasons"],
        requires_verified_seller=state["requires_verified_seller"],
        max_checkout_value_cents=state["max_checkout_value_cents"],
        package_weight_grams=state.get("package_weight_grams"),
        package_length_cm=state.get("package_length_cm"),
        package_width_cm=state.get("package_width_cm"),
        package_height_cm=state.get("package_height_cm"),
    )


def category_policy_to_type(category, policy) -> CategoryCommercePolicyType:
    return CategoryCommercePolicyType(
        category_id=category.slug,
        mode=policy.mode,
        requires_verified_seller=policy.requires_verified_seller,
        max_checkout_value_cents=policy.max_checkout_value_cents,
        shipping_allowed=policy.shipping_allowed,
        local_delivery_allowed=policy.local_delivery_allowed,
        pickup_allowed=policy.pickup_allowed,
    )


def payment_account_to_type(account) -> SellerPaymentAccountType:
    return SellerPaymentAccountType(
        provider=account.provider,
        recipient_id=account.provider_recipient_id,
        status=account.status,
        payout_method=account.payout_method or None,
        payout_destination_masked=account.payout_destination_masked or None,
        payouts_enabled=account.payouts_enabled,
        kyc_url=account.kyc_url or None,
    )


def wallet_to_type(wallet: dict) -> SellerWalletType:
    return SellerWalletType(**wallet)


def payment_to_type(payment) -> CommercePaymentType:
    return CommercePaymentType(
        id=str(payment.id),
        method=payment.method,
        status=payment.status,
        amount_cents=payment.amount_cents,
        provider=payment.provider,
        provider_status=payment.provider_status or None,
        checkout_data=payment.checkout_data,
        paid_at=payment.paid_at,
    )


def rider_summary_to_type(rider) -> DeliveryRiderSummaryType:
    return DeliveryRiderSummaryType(
        id=str(rider.id),
        user_id=str(rider.user_id),
        name=rider.user.full_name or rider.user.email,
        active=rider.active,
    )


def rider_admin_to_type(rider) -> DeliveryRiderAdminType:
    return DeliveryRiderAdminType(
        id=str(rider.id),
        user_id=str(rider.user_id),
        name=rider.user.full_name or rider.user.email,
        email=rider.user.email,
        active=rider.active,
    )


def shipment_to_type(shipment, *, buyer_view: bool = False) -> ShipmentType:
    try:
        assignment = shipment.delivery_assignment
    except Exception:
        assignment = None
    rider = assignment.rider if assignment and assignment.rider_id else None
    return ShipmentType(
        status=shipment.status,
        carrier=shipment.carrier or None,
        tracking_code=shipment.tracking_code or None,
        delivered_at=shipment.delivered_at,
        assigned_at=assignment.assigned_at if assignment else None,
        confirmation_source=(assignment.confirmation_source or None) if assignment else None,
        delivery_pin=buyer_delivery_pin(shipment) if buyer_view else None,
        rider=rider_summary_to_type(rider) if rider else None,
    )


def settlement_to_type(settlement) -> SettlementType:
    return SettlementType(
        status=settlement.status,
        amount_cents=settlement.amount_cents,
        release_after=settlement.release_after,
        payout_requested_at=settlement.payout_requested_at,
        paid_at=settlement.paid_at,
    )


def order_to_type(
    order,
    *,
    buyer_view: bool = True,
    include_shipping_address: bool | None = None,
) -> OrderType:
    payment = order.payments.order_by("-created_at").first()
    try:
        shipment = order.shipment
    except Exception:
        shipment = None
    try:
        settlement = order.settlement
    except Exception:
        settlement = None
    snapshot = dict(order.listing_snapshot or {})
    # Local-delivery PINs must never be read from listing snapshots. Existing
    # non-local test/legacy data keeps its old buyer-only behavior for backward
    # compatibility, while seller/admin views always strip the field.
    if not buyer_view or order.fulfillment_method == "local_delivery":
        snapshot.pop("delivery_pin", None)
    if include_shipping_address is None:
        include_shipping_address = buyer_view
    return OrderType(
        id=str(order.id),
        reference=order.reference,
        buyer_id=str(order.buyer_id),
        seller_id=str(order.seller_id),
        listing_id=str(order.listing_id),
        status=order.status,
        fulfillment_method=order.fulfillment_method,
        quantity=order.quantity,
        unit_price_cents=order.unit_price_cents,
        subtotal_cents=order.subtotal_cents,
        shipping_amount_cents=order.shipping_amount_cents,
        marketplace_fee_cents=order.marketplace_fee_cents,
        seller_proceeds_cents=order.seller_proceeds_cents,
        total_cents=order.total_cents,
        currency=order.currency,
        shipping_address=order.shipping_address if include_shipping_address else {},
        listing_snapshot=snapshot,
        payment=payment_to_type(payment) if payment else None,
        shipment=shipment_to_type(shipment, buyer_view=buyer_view) if shipment else None,
        settlement=settlement_to_type(settlement) if settlement else None,
        created_at=order.created_at,
        paid_at=order.paid_at,
        shipped_at=order.shipped_at,
        delivered_at=order.delivered_at,
        completed_at=order.completed_at,
    )


def dispute_to_type(dispute) -> DisputeType:
    return DisputeType(
        id=str(dispute.id),
        order_id=str(dispute.order_id),
        reason=dispute.reason,
        description=dispute.description,
        status=dispute.status,
        created_at=dispute.created_at,
    )
