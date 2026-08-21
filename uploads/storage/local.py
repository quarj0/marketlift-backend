from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from django.conf import settings
from .base import StorageBackend, StoredObjectInfo, UploadTarget


class LocalStorageBackend(StorageBackend):
    """Development filesystem backend."""

    def __init__(self, alias: str = "default"):
        self.alias = alias

    supports_proxy_upload = True

    @property
    def root(self) -> Path:
        root = Path(settings.MARKETLIFT_LOCAL_UPLOAD_ROOT).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _path(self, object_key: str) -> Path:
        relative = PurePosixPath(object_key)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe object key.")
        candidate = (self.root / Path(*relative.parts)).resolve()
        if self.root != candidate and self.root not in candidate.parents:
            raise ValueError("Unsafe object key.")
        return candidate

    def prepare_upload(self, asset, *, request=None) -> UploadTarget:
        path = f"/api/v1/uploads/{asset.id}/content/"
        url = request.build_absolute_uri(path) if request is not None else path
        return UploadTarget(
            method="PUT",
            url=url,
            headers={"Content-Type": asset.mime_type},
        )

    def store(
        self, asset, stream, *, content_length: int | None = None
    ) -> StoredObjectInfo:
        path = self._path(asset.object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        with path.open("wb") as destination:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
                destination.write(chunk)
        return StoredObjectInfo(
            size=size, content_type=asset.mime_type, checksum_sha256=digest.hexdigest()
        )

    def stat(self, asset) -> StoredObjectInfo:
        path = self._path(asset.object_key)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(asset.object_key)
        return StoredObjectInfo(size=path.stat().st_size, content_type=asset.mime_type)

    def open(self, asset):
        return self._path(asset.object_key).open("rb")

    def delete(self, asset) -> None:
        path = self._path(asset.object_key)
        try:
            path.unlink()
        except FileNotFoundError:
            return
