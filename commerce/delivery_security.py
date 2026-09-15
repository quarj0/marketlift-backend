from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ValidationError


_CONTEXT = b"marketlift:delivery-pin:v1"


def _fernet() -> Fernet:
    """Derive a purpose-separated encryption key from Django's secret key."""
    secret = str(settings.SECRET_KEY).encode("utf-8")
    digest = hashlib.sha256(_CONTEXT + b":" + secret).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_delivery_pin(pin: str) -> str:
    value = str(pin or "").strip()
    if len(value) != 6 or not value.isdigit():
        raise ValidationError({"deliveryPin": "Delivery PIN must contain six digits."})
    return _fernet().encrypt(value.encode("ascii")).decode("ascii")


def decrypt_delivery_pin(ciphertext: str) -> str | None:
    value = str(ciphertext or "").strip()
    if not value:
        return None
    try:
        pin = _fernet().decrypt(value.encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError, UnicodeError):
        return None
    if len(pin) != 6 or not pin.isdigit():
        return None
    return pin
