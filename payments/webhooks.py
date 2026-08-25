import hashlib
import hmac


def parse_mercado_pago_signature(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in (value or "").split(","):
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        result[key.strip()] = val.strip()
    return result


def valid_mercado_pago_signature(
    *, data_id: str, request_id: str, signature: str, secret: str
) -> bool:
    if not data_id or not secret:
        return False
    values = parse_mercado_pago_signature(signature)
    timestamp = values.get("ts")
    received = values.get("v1")
    if not timestamp or not received:
        return False

    manifest = f"id:{data_id};"
    if request_id:
        manifest += f"request-id:{request_id};"
    manifest += f"ts:{timestamp};"

    expected = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received)


def valid_paystack_signature(*, body: bytes, signature: str, secret: str) -> bool:
    """Validate Paystack's x-paystack-signature HMAC-SHA512 header."""
    if not body or not signature or not secret:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature.strip())
