from __future__ import annotations

from dataclasses import dataclass, field
from typing import BinaryIO


@dataclass(frozen=True)
class UploadTarget:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StoredObjectInfo:
    size: int
    content_type: str = ""
    checksum_sha256: str = ""


class StorageBackend:
    """Provider-neutral object storage contract used by Marketlift domains."""

    supports_proxy_upload = False

    def prepare_upload(self, asset, *, request=None) -> UploadTarget:
        raise NotImplementedError

    def store(
        self, asset, stream: BinaryIO, *, content_length: int | None = None
    ) -> StoredObjectInfo:
        raise NotImplementedError

    def stat(self, asset) -> StoredObjectInfo:
        raise NotImplementedError

    def open(self, asset) -> BinaryIO:
        raise NotImplementedError

    def access_url(self, asset, *, request=None) -> str | None:
        """Return a temporary/provider URL, or None to stream through Django."""
        return None

    def delete(self, asset) -> None:
        raise NotImplementedError
