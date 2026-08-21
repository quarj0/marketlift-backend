from __future__ import annotations

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError

from .contracts import LocationCandidate
from .validators import normalize_country_code, validate_coordinates

_SALT = "marketlift.location.selection.v1"


def encode_location_token(candidate: LocationCandidate) -> str:
    payload = {
        "lat": round(float(candidate.latitude), 7),
        "lng": round(float(candidate.longitude), 7),
        "country_code": normalize_country_code(candidate.country_code),
        "state": candidate.state[:100],
        "state_code": candidate.state_code[:8].upper(),
        "city": candidate.city[:100],
        "district": candidate.district[:120],
        "provider": candidate.provider[:40],
        "provider_id": candidate.provider_id[:120],
    }
    return signing.dumps(payload, salt=_SALT, compress=True)


def decode_location_token(token: str) -> dict:
    try:
        payload = signing.loads(
            token,
            salt=_SALT,
            max_age=int(getattr(settings, "MARKETLIFT_LOCATION_TOKEN_MAX_AGE_SECONDS", 86400)),
        )
    except signing.BadSignature as exc:
        raise ValidationError({"location_token": "Location selection is invalid or expired."}) from exc
    if not isinstance(payload, dict):
        raise ValidationError({"location_token": "Location selection is invalid."})
    lat, lng = validate_coordinates(payload.get("lat"), payload.get("lng"), required=True)
    return {
        "latitude": lat,
        "longitude": lng,
        "country_code": normalize_country_code(payload.get("country_code")),
        "state": str(payload.get("state") or "").strip()[:100],
        "state_code": str(payload.get("state_code") or "").strip().upper()[:8],
        "city": str(payload.get("city") or "").strip()[:100],
        "district": str(payload.get("district") or "").strip()[:120],
        "provider": str(payload.get("provider") or "").strip()[:40],
        "provider_id": str(payload.get("provider_id") or "").strip()[:120],
    }
