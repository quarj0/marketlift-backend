from datetime import datetime
import strawberry


@strawberry.type
class PaymentType:
    id: strawberry.ID
    reference: str
    seller_id: strawberry.ID
    seller_name: str
    purpose: str
    method: str
    status: str
    amount: float
    currency: str
    provider: str
    provider_order_id: str | None
    provider_status: str | None
    provider_status_detail: str | None
    checkout_data: strawberry.scalars.JSON
    plan_id: str | None
    billing_cycle: str | None
    listing_id: strawberry.ID | None
    promotion_id: str | None
    created_at: datetime
    paid_at: datetime | None
    failed_at: datetime | None
    refunded_at: datetime | None


@strawberry.type
class PaymentSummaryType:
    paid_total: float
    refunded_total: float
    paid_count: int
    failed_count: int
    pending_count: int
    success_rate: float
