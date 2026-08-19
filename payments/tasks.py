from celery import shared_task

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
    provider = get_payment_provider()
    if provider.name != "mercado_pago":
        return {"ignored": True, "reason": "provider_inactive"}
    payment = Payment.objects.filter(
        provider="mercado_pago", provider_order_id=order_id
    ).first()
    if not payment:
        return {"ignored": True, "reason": "payment_not_found"}
    result = provider.get_order(order_id)
    sync_payment_from_provider(payment=payment, result=result)
    return {"payment_id": str(payment.id), "status": payment.status}
