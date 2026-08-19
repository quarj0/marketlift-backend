from celery import shared_task

from .services import expire_abandoned_uploads


@shared_task(name="uploads.tasks.cleanup_expired_uploads")
def cleanup_expired_uploads():
    return expire_abandoned_uploads()


@shared_task(
    bind=True,
    autoretry_for=(OSError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def process_upload_image(self, asset_id):
    from .models import UploadAsset
    from .processing import process_image_asset

    try:
        asset = UploadAsset.objects.get(pk=asset_id)
    except UploadAsset.DoesNotExist:
        return 0
    return process_image_asset(asset)
