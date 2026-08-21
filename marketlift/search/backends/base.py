from __future__ import annotations

from abc import ABC, abstractmethod

from marketlift.search.contracts import (
    ParsedMarketplaceQuery,
    SearchPage,
    SearchRequest,
)


class ListingSearchBackend(ABC):
    @abstractmethod
    def search(
        self, request: SearchRequest, parsed: ParsedMarketplaceQuery
    ) -> SearchPage:
        raise NotImplementedError
