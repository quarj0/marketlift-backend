from datetime import datetime

import strawberry
from strawberry.scalars import JSON


@strawberry.type
class ListingCommerceType:
    mode: str
    checkout_enabled: bool
    inspection_allowed: bool
    stock_quantity: int
    fulfillment_methods: list[str]
    reasons: list[str]
    requires_verified_seller: bool
    max_checkout_value_cents: int | None
    package_weight_grams: int | None
    package_length_cm: int | None
    package_width_cm: int | None
    package_height_cm: int | None


@strawberry.type
class CheckoutQuoteType:
    listing_id: strawberry.ID
    fulfillment_method: str
    quantity: int
    subtotal_cents: int
    shipping_amount_cents: int
    total_cents: int
    currency: str


@strawberry.type
class CategoryCommercePolicyType:
    category_id: str
    mode: str
    requires_verified_seller: bool
    max_checkout_value_cents: int | None
    shipping_allowed: bool
    local_delivery_allowed: bool
    pickup_allowed: bool


@strawberry.type
class SellerPaymentAccountType:
    provider: str
    recipient_id: str | None
    status: str
    payout_method: str | None
    payout_destination_masked: str | None
    payouts_enabled: bool
    kyc_url: str | None


@strawberry.type
class SellerWalletType:
    pending_cents: int
    available_cents: int
    payout_requested_cents: int
    paid_out_cents: int
    currency: str


@strawberry.type
class CommercePaymentType:
    id: strawberry.ID
    method: str
    status: str
    amount_cents: int
    provider: str
    provider_status: str | None
    checkout_data: JSON
    paid_at: datetime | None


@strawberry.type
class DeliveryRiderSummaryType:
    id: strawberry.ID
    user_id: strawberry.ID
    name: str
    active: bool


@strawberry.type
class DeliveryRiderAdminType:
    id: strawberry.ID
    user_id: strawberry.ID
    name: str
    email: str
    active: bool


@strawberry.type
class ShipmentType:
    status: str
    carrier: str | None
    tracking_code: str | None
    delivered_at: datetime | None
    assigned_at: datetime | None
    confirmation_source: str | None
    delivery_pin: str | None
    rider: DeliveryRiderSummaryType | None


@strawberry.type
class SettlementType:
    status: str
    amount_cents: int
    release_after: datetime | None
    payout_requested_at: datetime | None
    paid_at: datetime | None


@strawberry.type
class OrderType:
    id: strawberry.ID
    reference: str
    buyer_id: strawberry.ID
    seller_id: strawberry.ID
    listing_id: strawberry.ID
    status: str
    fulfillment_method: str
    quantity: int
    unit_price_cents: int
    subtotal_cents: int
    shipping_amount_cents: int
    marketplace_fee_cents: int
    seller_proceeds_cents: int
    total_cents: int
    currency: str
    shipping_address: JSON
    listing_snapshot: JSON
    payment: CommercePaymentType | None
    shipment: ShipmentType | None
    settlement: SettlementType | None
    created_at: datetime
    paid_at: datetime | None
    shipped_at: datetime | None
    delivered_at: datetime | None
    completed_at: datetime | None


@strawberry.type
class CommerceCurrencySummaryType:
    currency: str
    gross_cents: int
    marketplace_fee_cents: int
    held_seller_funds_cents: int


@strawberry.type
class AdminCommerceSummaryType:
    currencies: list[CommerceCurrencySummaryType]
    open_disputes: int


@strawberry.type
class CheckoutPayload:
    order: OrderType
    payment: CommercePaymentType


@strawberry.type
class PayoutPayload:
    transfer_id: str
    amount_cents: int
    status: str


@strawberry.type
class DisputeType:
    id: strawberry.ID
    order_id: strawberry.ID
    reason: str
    description: str
    status: str
    created_at: datetime
