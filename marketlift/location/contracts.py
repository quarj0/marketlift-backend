from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LocationCandidate:
    latitude: float
    longitude: float
    label: str
    country_code: str
    country: str = ""
    state: str = ""
    state_code: str = ""
    city: str = ""
    district: str = ""
    provider: str = ""
    provider_id: str = ""

    def as_dict(self, *, token: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "label": self.label,
            "country": self.country or None,
            "countryCode": self.country_code or None,
            "state": self.state or None,
            "stateCode": self.state_code or None,
            "city": self.city or None,
            "district": self.district or None,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "provider": self.provider or None,
        }
        if token:
            payload["locationToken"] = token
        return payload
