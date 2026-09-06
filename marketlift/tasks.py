from celery import shared_task
from django.core.cache import cache
from django.utils import timezone


@shared_task(ignore_result=True)
def worker_heartbeat():
    # Execution proves beat can publish and a worker can consume the default queue.
    cache.set("marketlift:worker-heartbeat", timezone.now().isoformat(), timeout=180)


@shared_task(name="marketlift.tasks.cleanup_expired_sessions")
def cleanup_expired_sessions():
    from django.contrib.sessions.models import Session

    deleted, _ = Session.objects.filter(expire_date__lt=timezone.now()).delete()
    return deleted
