from __future__ import annotations

from django.core.exceptions import ValidationError

from .base import GeocoderBackend


class DisabledGeocoder(GeocoderBackend):
    def _error(self):
        raise ValidationError({"location": "Location resolver is not configured."})

    def geocode(self, query: str, *, limit: int = 5, country_code: str | None = None):
        self._error()

    def reverse(self, latitude: float, longitude: float):
        self._error()
