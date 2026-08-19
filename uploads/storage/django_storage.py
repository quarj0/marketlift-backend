import hashlib
from django.conf import settings
from django.core.files.base import File
from django.core.files.storage import storages
from .base import StorageBackend, StoredObjectInfo, UploadTarget


class DjangoStorageBackend(StorageBackend):
    """Provider-neutral bridge to any Django STORAGES backend configured by deployment."""

    supports_proxy_upload = True

    @property
    def storage(self):
        return storages[
            getattr(settings, "MARKETLIFT_DJANGO_STORAGE_ALIAS", "marketlift_media")
        ]

    def prepare_upload(self, asset, *, request=None):
        path = f"/api/v1/uploads/{asset.id}/content/"
        return UploadTarget(
            method="PUT",
            url=request.build_absolute_uri(path) if request else path,
            headers={"Content-Type": asset.mime_type},
        )

    def store(self, asset, stream, *, content_length=None):
        digest = hashlib.sha256()
        data = stream.read()
        digest.update(data)
        from io import BytesIO

        if self.storage.exists(asset.object_key):
            self.storage.delete(asset.object_key)
        self.storage.save(
            asset.object_key,
            File(BytesIO(data), name=asset.object_key.rsplit("/", 1)[-1]),
        )
        return StoredObjectInfo(
            size=len(data),
            content_type=asset.mime_type,
            checksum_sha256=digest.hexdigest(),
        )

    def stat(self, asset):
        if not self.storage.exists(asset.object_key):
            raise FileNotFoundError(asset.object_key)
        return StoredObjectInfo(
            size=self.storage.size(asset.object_key), content_type=asset.mime_type
        )

    def open(self, asset):
        return self.storage.open(asset.object_key, "rb")

    def access_url(self, asset, *, request=None):
        try:
            return self.storage.url(asset.object_key)
        except Exception:
            return None

    def delete(self, asset):
        if self.storage.exists(asset.object_key):
            self.storage.delete(asset.object_key)
