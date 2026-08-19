from celery import shared_task
from django.contrib.sessions.models import Session
from django.utils import timezone


@shared_task(name="marketlift.tasks.cleanup_expired_sessions")
def cleanup_expired_sessions():
    deleted, _ = Session.objects.filter(expire_date__lt=timezone.now()).delete()
    return deleted
