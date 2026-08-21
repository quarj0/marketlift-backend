from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from io import BytesIO
from urllib.parse import quote, urlencode, urlsplit

import httpx
from django.conf import settings

from .base import StorageBackend, StoredObjectInfo, UploadTarget

_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _aws_quote(value: str) -> str:
    return quote(str(value), safe="-_.~")


def _hmac(key: bytes, value: str) -> bytes:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()


class S3CompatibleStorageBackend(StorageBackend):
    """Provider-neutral S3-compatible storage adapter.

    Domain code uses logical aliases such as ``temp``, ``public``, ``private``
    and ``evidence``. This implementation intentionally signs S3 requests
    itself instead of depending on a provider SDK, keeping the storage layer
    portable across Cloudflare R2 and other SigV4-compatible object stores.
    """

    supports_proxy_upload = False
    service = "s3"

    def __init__(self, alias: str = "default"):
        self.alias = alias

    @property
    def bucket(self) -> str:
        buckets = getattr(settings, "MARKETLIFT_STORAGE_BUCKETS", {})
        bucket = (buckets.get(self.alias) or buckets.get("default") or "").strip()
        if not bucket:
            raise RuntimeError(
                f"No object-storage bucket is configured for alias '{self.alias}'."
            )
        return bucket

    @property
    def endpoint(self) -> str:
        endpoint = str(getattr(settings, "MARKETLIFT_S3_ENDPOINT_URL", "")).strip()
        if not endpoint:
            raise RuntimeError("S3-compatible storage endpoint is not configured.")
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError("S3-compatible storage endpoint is invalid.")
        return endpoint.rstrip("/")

    @property
    def access_key(self) -> str:
        value = str(getattr(settings, "MARKETLIFT_S3_ACCESS_KEY_ID", "")).strip()
        if not value:
            raise RuntimeError("S3-compatible access key is not configured.")
        return value

    @property
    def secret_key(self) -> str:
        value = str(
            getattr(settings, "MARKETLIFT_S3_SECRET_ACCESS_KEY", "")
        ).strip()
        if not value:
            raise RuntimeError("S3-compatible secret key is not configured.")
        return value

    @property
    def region(self) -> str:
        return str(getattr(settings, "MARKETLIFT_S3_REGION", "auto")).strip() or "auto"

    def _object_url_parts(self, object_key: str):
        parsed = urlsplit(self.endpoint)
        base_path = parsed.path.rstrip("/")
        encoded_bucket = _aws_quote(self.bucket)
        encoded_key = "/".join(_aws_quote(part) for part in str(object_key).split("/"))
        path = f"{base_path}/{encoded_bucket}/{encoded_key}" or "/"
        return parsed, path

    def _object_url(self, object_key: str) -> str:
        parsed, path = self._object_url_parts(object_key)
        return f"{parsed.scheme}://{parsed.netloc}{path}"

    def _signing_key(self, date_stamp: str) -> bytes:
        key_date = _hmac(("AWS4" + self.secret_key).encode("utf-8"), date_stamp)
        key_region = _hmac(key_date, self.region)
        key_service = _hmac(key_region, self.service)
        return _hmac(key_service, "aws4_request")

    def _credential_scope(self, date_stamp: str) -> str:
        return f"{date_stamp}/{self.region}/{self.service}/aws4_request"

    def _presigned_url(
        self,
        *,
        method: str,
        object_key: str,
        expires: int,
        content_type: str | None = None,
        now: datetime | None = None,
    ) -> str:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        amz_date = current.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = current.strftime("%Y%m%d")
        parsed, canonical_uri = self._object_url_parts(object_key)

        canonical_headers = {"host": parsed.netloc}
        if content_type:
            canonical_headers["content-type"] = content_type.strip()
        signed_header_names = sorted(canonical_headers)
        signed_headers = ";".join(signed_header_names)
        canonical_headers_text = "".join(
            f"{name}:{' '.join(str(canonical_headers[name]).split())}\n"
            for name in signed_header_names
        )

        query = {
            "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
            "X-Amz-Credential": f"{self.access_key}/{self._credential_scope(date_stamp)}",
            "X-Amz-Date": amz_date,
            "X-Amz-Expires": str(max(60, min(int(expires), 3600))),
            "X-Amz-SignedHeaders": signed_headers,
        }
        canonical_query = urlencode(
            sorted(query.items()), quote_via=quote, safe="-_.~"
        )
        canonical_request = "\n".join(
            [
                method.upper(),
                canonical_uri,
                canonical_query,
                canonical_headers_text,
                signed_headers,
                "UNSIGNED-PAYLOAD",
            ]
        )
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                self._credential_scope(date_stamp),
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signature = hmac.new(
            self._signing_key(date_stamp),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return (
            f"{parsed.scheme}://{parsed.netloc}{canonical_uri}?"
            f"{canonical_query}&X-Amz-Signature={signature}"
        )

    def _signed_headers(
        self,
        *,
        method: str,
        object_key: str,
        payload_hash: str,
        extra_headers: dict[str, str] | None = None,
        now: datetime | None = None,
    ) -> dict[str, str]:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        amz_date = current.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = current.strftime("%Y%m%d")
        parsed, canonical_uri = self._object_url_parts(object_key)

        headers = {
            "host": parsed.netloc,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        for name, value in (extra_headers or {}).items():
            headers[name.lower()] = " ".join(str(value).strip().split())

        signed_header_names = sorted(headers)
        signed_headers = ";".join(signed_header_names)
        canonical_headers_text = "".join(
            f"{name}:{headers[name]}\n" for name in signed_header_names
        )
        canonical_request = "\n".join(
            [
                method.upper(),
                canonical_uri,
                "",
                canonical_headers_text,
                signed_headers,
                payload_hash,
            ]
        )
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                self._credential_scope(date_stamp),
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signature = hmac.new(
            self._signing_key(date_stamp),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers["authorization"] = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.access_key}/{self._credential_scope(date_stamp)}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return headers

    def _request(
        self,
        method: str,
        asset,
        *,
        content: bytes | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        payload = content or b""
        payload_hash = hashlib.sha256(payload).hexdigest() if payload else _EMPTY_SHA256
        headers = self._signed_headers(
            method=method,
            object_key=asset.object_key,
            payload_hash=payload_hash,
            extra_headers=extra_headers,
        )
        timeout = httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)
        response = httpx.request(
            method,
            self._object_url(asset.object_key),
            headers=headers,
            content=payload if method.upper() in {"PUT", "POST"} else None,
            timeout=timeout,
        )
        if response.status_code == 404:
            raise FileNotFoundError(asset.object_key)
        if response.is_error:
            raise RuntimeError(
                f"Object storage request failed with HTTP {response.status_code}."
            )
        return response

    def prepare_upload(self, asset, *, request=None) -> UploadTarget:
        ttl = int(getattr(settings, "MARKETLIFT_PRESIGNED_UPLOAD_TTL_SECONDS", 900))
        return UploadTarget(
            method="PUT",
            url=self._presigned_url(
                method="PUT",
                object_key=asset.object_key,
                expires=ttl,
                content_type=asset.mime_type,
            ),
            headers={"Content-Type": asset.mime_type},
        )

    def store(self, asset, stream, *, content_length=None) -> StoredObjectInfo:
        data = stream.read()
        digest = hashlib.sha256(data).hexdigest()
        public_alias = getattr(settings, "MARKETLIFT_PUBLIC_STORAGE_ALIAS", "public")
        cache_control = (
            "public, max-age=31536000, immutable"
            if self.alias == public_alias
            else "private, no-store"
        )
        self._request(
            "PUT",
            asset,
            content=data,
            extra_headers={
                "content-type": asset.mime_type,
                "cache-control": cache_control,
                "x-amz-meta-sha256": digest,
            },
        )
        return StoredObjectInfo(
            size=len(data),
            content_type=asset.mime_type,
            checksum_sha256=digest,
        )

    def stat(self, asset) -> StoredObjectInfo:
        response = self._request("HEAD", asset)
        return StoredObjectInfo(
            size=int(response.headers.get("content-length") or 0),
            content_type=response.headers.get("content-type") or asset.mime_type,
            checksum_sha256=response.headers.get("x-amz-meta-sha256") or "",
        )

    def open(self, asset):
        response = self._request("GET", asset)
        return BytesIO(response.content)

    def access_url(self, asset, *, request=None) -> str | None:
        public_alias = getattr(settings, "MARKETLIFT_PUBLIC_STORAGE_ALIAS", "public")
        base_url = getattr(settings, "MARKETLIFT_PUBLIC_ASSET_BASE_URL", "").strip()
        if self.alias == public_alias and base_url:
            encoded_key = "/".join(
                _aws_quote(part) for part in str(asset.object_key).split("/")
            )
            return f"{base_url.rstrip('/')}/{encoded_key}"

        ttl = int(getattr(settings, "MARKETLIFT_PRESIGNED_DOWNLOAD_TTL_SECONDS", 300))
        return self._presigned_url(
            method="GET",
            object_key=asset.object_key,
            expires=ttl,
        )

    def delete(self, asset) -> None:
        try:
            self._request("DELETE", asset)
        except FileNotFoundError:
            return
