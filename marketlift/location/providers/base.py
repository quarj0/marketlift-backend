from __future__ import annotations

from abc import ABC, abstractmethod

from marketlift.location.contracts import LocationCandidate


class GeocoderBackend(ABC):
    @abstractmethod
    def geocode(self, query: str, *, limit: int = 5) -> list[LocationCandidate]:
        raise NotImplementedError

    @abstractmethod
    def reverse(self, latitude: float, longitude: float) -> LocationCandidate | None:
        raise NotImplementedError
