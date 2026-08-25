from celery import shared_task
from django.conf import settings

from payments.models import Payment
from payments.providers import get_payment_provider
from payments.providers.base import PaymentProviderError
from payments.services import sync_payment_from_provider


@shared_task(
    bind=True,
    autoretry_for=(PaymentProviderError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def sync_mercado_pago_order(self, order_id: str):
    if not getattr(settings, "MARKETLIFT_PAYMENTS_ENABLED", False):
        return {"ignored": True, "reason": "payments_disabled"}
    provider = get_payment_provider(name="mercado_pago")
    payment = Payment.objects.filter(
        provider="mercado_pago", provider_order_id=order_id
    ).first()
    if not payment:
        return {"ignored": True, "reason": "payment_not_found"}
    result = provider.get_order(order_id)
    sync_payment_from_provider(payment=payment, result=result)
    return {"payment_id": str(payment.id), "status": payment.status}


@shared_task(
    bind=True,
    autoretry_for=(PaymentProviderError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def sync_paystack_transaction(self, reference: str):
    if not getattr(settings, "MARKETLIFT_PAYMENTS_ENABLED", False):
        return {"ignored": True, "reason": "payments_disabled"}
    provider = get_payment_provider(name="paystack")
    payment = Payment.objects.filter(
        provider="paystack", provider_order_id=reference
    ).first()
    if payment is None:
        # The initialize response always uses our own payment.reference as the
        # Paystack reference. This fallback also handles a webhook racing the DB
        # update that stores provider_order_id.
        payment = Payment.objects.filter(
            provider="paystack", reference=reference
        ).first()
    if not payment:
        return {"ignored": True, "reason": "payment_not_found"}
    result = provider.get_order(reference)
    sync_payment_from_provider(payment=payment, result=result)
    return {"payment_id": str(payment.id), "status": payment.status}


@shared_task(
    bind=True,
    autoretry_for=(PaymentProviderError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def reconcile_pending_payments(self):
    if not getattr(settings, "MARKETLIFT_PAYMENTS_ENABLED", False):
        return {"checked": 0, "reason": "payments_disabled"}
    checked = 0
    pending = (
        Payment.objects.filter(status=Payment.Status.PENDING)
        .exclude(provider_order_id="")
        .exclude(provider__in=("", "mock"))[:100]
    )
    for payment in pending:
        provider = get_payment_provider(name=payment.provider)
        result = provider.get_order(payment.provider_order_id)
        sync_payment_from_provider(payment=payment, result=result)
        checked += 1
    return {"checked": checked}
