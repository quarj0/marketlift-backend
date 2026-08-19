from celery import shared_task

from subscriptions.services import expire_due_subscriptions


@shared_task
def expire_due_seller_subscriptions():
    return {"expired": expire_due_subscriptions()}
