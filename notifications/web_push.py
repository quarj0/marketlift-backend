from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes, hmac, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand

_DEFAULT_ENDPOINT_SUFFIXES = (
    "fcm.googleapis.com",
    "push.services.mozilla.com",
    "updates.push.services.mozilla.com",
    "web.push.apple.com",
    "push.apple.com",
    "notify.windows.com",
)


class WebPushError(Exception):
    pass


@dataclass(slots=True)
class WebPushHTTPError(WebPushError):
    status_code: int
    message: str
    permanent_subscription_failure: bool = False
    retryable: bool = False

    def __str__(self) -> str:
        return self.message


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    value = (value or "").strip()
    if not value:
        raise ValueError("Missing base64url value.")
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + padding)


def endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


def allowed_endpoint_suffixes() -> tuple[str, ...]:
    configured = os.getenv("MARKETLIFT_WEB_PUSH_ENDPOINT_SUFFIXES", "").strip()
    if not configured:
        return _DEFAULT_ENDPOINT_SUFFIXES
    return tuple(
        suffix.strip().lower().lstrip(".")
        for suffix in configured.split(",")
        if suffix.strip()
    )


def validate_subscription_endpoint(endpoint: str) -> str:
    endpoint = (endpoint or "").strip()
    if not endpoint or len(endpoint) > 4096:
        raise ValueError("Invalid push subscription endpoint.")
    parsed = urlsplit(endpoint)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("Push subscription endpoint must use HTTPS.")
    hostname = parsed.hostname.lower().rstrip(".")
    allowed = allowed_endpoint_suffixes()
    if not any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in allowed):
        raise ValueError("Unsupported push service endpoint.")
    return endpoint


def validate_subscription_keys(*, p256dh: str, auth: str) -> tuple[str, str]:
    p256dh = (p256dh or "").strip()
    auth = (auth or "").strip()
    try:
        public_bytes = _b64url_decode(p256dh)
        auth_bytes = _b64url_decode(auth)
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public_bytes)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid Web Push subscription keys.") from exc
    if len(public_bytes) != 65 or public_bytes[0] != 0x04:
        raise ValueError("Invalid Web Push p256dh key.")
    if len(auth_bytes) < 16 or len(auth_bytes) > 32:
        raise ValueError("Invalid Web Push auth secret.")
    return p256dh, auth


def _vapid_private_key() -> ec.EllipticCurvePrivateKey | None:
    raw = os.getenv("MARKETLIFT_VAPID_PRIVATE_KEY", "").strip()
    if not raw:
        return None
    try:
        private_bytes = _b64url_decode(raw)
    except Exception as exc:
        raise WebPushError("MARKETLIFT_VAPID_PRIVATE_KEY is not valid base64url.") from exc
    if len(private_bytes) != 32:
        raise WebPushError("MARKETLIFT_VAPID_PRIVATE_KEY must decode to 32 bytes.")
    private_value = int.from_bytes(private_bytes, "big")
    try:
        return ec.derive_private_key(private_value, ec.SECP256R1())
    except ValueError as exc:
        raise WebPushError("MARKETLIFT_VAPID_PRIVATE_KEY is not a valid P-256 key.") from exc


def web_push_configured() -> bool:
    return bool(os.getenv("MARKETLIFT_VAPID_PRIVATE_KEY", "").strip())


def web_push_public_key() -> str:
    private_key = _vapid_private_key()
    if private_key is None:
        return ""
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return _b64url_encode(public_bytes)


def _hkdf_extract(*, salt: bytes, ikm: bytes) -> bytes:
    mac = hmac.HMAC(salt, hashes.SHA256())
    mac.update(ikm)
    return mac.finalize()


def _hkdf_expand(*, prk: bytes, info: bytes, length: int) -> bytes:
    return HKDFExpand(
        algorithm=hashes.SHA256(),
        length=length,
        info=info,
    ).derive(prk)


def _encrypt_payload(*, payload: bytes, p256dh: str, auth: str) -> bytes:
    # RFC 8291 + RFC 8188, aes128gcm content coding. We intentionally keep a
    # single record because browser push payloads must stay small anyway.
    if len(payload) > 3000:
        raise WebPushError("Web Push payload is too large.")

    client_public_bytes = _b64url_decode(p256dh)
    auth_secret = _b64url_decode(auth)
    client_public = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), client_public_bytes
    )

    server_private = ec.generate_private_key(ec.SECP256R1())
    server_public_bytes = server_private.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    shared_secret = server_private.exchange(ec.ECDH(), client_public)

    prk_key = _hkdf_extract(salt=auth_secret, ikm=shared_secret)
    key_info = b"WebPush: info\x00" + client_public_bytes + server_public_bytes
    ikm = _hkdf_expand(prk=prk_key, info=key_info, length=32)

    salt = os.urandom(16)
    prk = _hkdf_extract(salt=salt, ikm=ikm)
    cek = _hkdf_expand(
        prk=prk,
        info=b"Content-Encoding: aes128gcm\x00",
        length=16,
    )
    nonce = _hkdf_expand(
        prk=prk,
        info=b"Content-Encoding: nonce\x00",
        length=12,
    )

    record_size = 4096
    plaintext = payload + b"\x02"
    if len(plaintext) + 16 > record_size:
        raise WebPushError("Web Push payload exceeds a single encrypted record.")
    ciphertext = AESGCM(cek).encrypt(nonce, plaintext, None)

    return (
        salt
        + record_size.to_bytes(4, "big")
        + bytes([len(server_public_bytes)])
        + server_public_bytes
        + ciphertext
    )


def _vapid_token(endpoint: str) -> tuple[str, str]:
    private_key = _vapid_private_key()
    if private_key is None:
        raise WebPushError("Web Push is not configured.")

    parsed = urlsplit(endpoint)
    audience = f"{parsed.scheme}://{parsed.netloc}"
    subject = os.getenv(
        "MARKETLIFT_VAPID_SUBJECT", "mailto:support@marketlift.com.br"
    ).strip()
    if not (subject.startswith("mailto:") or subject.startswith("https://")):
        raise WebPushError("MARKETLIFT_VAPID_SUBJECT must be mailto: or https://.")

    header = {"typ": "JWT", "alg": "ES256"}
    claims = {
        "aud": audience,
        "exp": int(time.time()) + 12 * 60 * 60,
        "sub": subject,
    }
    header_segment = _b64url_encode(
        json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    claims_segment = _b64url_encode(
        json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signing_input = f"{header_segment}.{claims_segment}".encode("ascii")
    der_signature = private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_signature)
    raw_signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    token = f"{header_segment}.{claims_segment}.{_b64url_encode(raw_signature)}"
    return token, web_push_public_key()


def build_notification_payload(notification) -> bytes:
    payload = {
        "id": str(notification.id),
        "type": notification.notification_type,
        "title": notification.title,
        "body": notification.body,
        "href": notification.href or "/notifications",
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def send_web_push(*, subscription, notification) -> None:
    endpoint = validate_subscription_endpoint(subscription.endpoint)
    validate_subscription_keys(p256dh=subscription.p256dh, auth=subscription.auth)
    encrypted = _encrypt_payload(
        payload=build_notification_payload(notification),
        p256dh=subscription.p256dh,
        auth=subscription.auth,
    )
    token, vapid_public_key = _vapid_token(endpoint)
    ttl = max(60, min(int(os.getenv("MARKETLIFT_WEB_PUSH_TTL_SECONDS", "86400")), 2419200))
    timeout = max(1.0, float(os.getenv("MARKETLIFT_WEB_PUSH_TIMEOUT_SECONDS", "10")))

    try:
        response = httpx.post(
            endpoint,
            content=encrypted,
            headers={
                "Authorization": f"vapid t={token}, k={vapid_public_key}",
                "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream",
                "TTL": str(ttl),
                "Urgency": "normal",
            },
            timeout=timeout,
            follow_redirects=False,
        )
    except httpx.HTTPError as exc:
        raise WebPushError(f"Push service request failed: {exc}") from exc

    if 200 <= response.status_code < 300:
        return
    body = response.text[:300].strip()
    message = f"Push service returned HTTP {response.status_code}"
    if body:
        message = f"{message}: {body}"
    if response.status_code in {404, 410}:
        raise WebPushHTTPError(
            response.status_code,
            message,
            permanent_subscription_failure=True,
        )
    if response.status_code == 429 or response.status_code >= 500:
        raise WebPushHTTPError(
            response.status_code,
            message,
            retryable=True,
        )
    raise WebPushHTTPError(response.status_code, message)
