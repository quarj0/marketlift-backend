from .types import PaymentType


def payment_to_type(p):
    return PaymentType(
        id=str(p.id),
        reference=p.reference,
        seller_id=str(p.seller_id),
        seller_name=str(p.seller),
        purpose=p.purpose,
        method=p.method,
        status=p.status,
        amount=float(p.amount),
        currency=p.currency,
        provider=p.provider,
        provider_order_id=p.provider_order_id or None,
        provider_status=p.provider_status or None,
        provider_status_detail=p.provider_status_detail or None,
        checkout_data=p.checkout_data or {},
        plan_id=p.seller_plan.code if p.seller_plan_id else None,
        billing_cycle=p.billing_cycle or None,
        listing_id=str(p.listing_id) if p.listing_id else None,
        promotion_id=p.promotion_product.code if p.promotion_product_id else None,
        created_at=p.created_at,
        paid_at=p.paid_at,
        failed_at=p.failed_at,
        refunded_at=p.refunded_at,
    )
