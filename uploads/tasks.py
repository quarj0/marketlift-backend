from celery import shared_task

from .services import expire_abandoned_uploads


@shared_task(name="uploads.tasks.cleanup_expired_uploads")
def cleanup_expired_uploads():
    return expire_abandoned_uploads()
