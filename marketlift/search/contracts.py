from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class ParsedMarketplaceQuery:
    original: str
    normalized: str
    core_tokens: tuple[str, ...] = ()
    specification_tokens: tuple[str, ...] = ()
    min_price: Decimal | None = None
    max_price: Decimal | None = None

    @property
    def has_text_anchor(self) -> bool:
        return bool(self.core_tokens)

    def interpreted_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "terms": list(self.core_tokens),
            "specifications": list(self.specification_tokens),
        }
        if self.min_price is not None:
            payload["minPrice"] = float(self.min_price)
        if self.max_price is not None:
            payload["maxPrice"] = float(self.max_price)
        return payload


@dataclass(frozen=True)
class SearchRequest:
    q: str = ""
    category: str | None = None
    region: str | None = None
    state: str | None = None
    city: str | None = None
    district: str | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    condition: str | None = None
    seller_type: str | None = None
    seller_id: str | None = None
    verified_only: bool = False
    date_listed: str | None = None
    attribute_filters: dict[str, Any] = field(default_factory=dict)
    sort: str = "relevant"
    page_size: int = 24
    cursor: str | None = None
    offset: int = 0
    # Internal-only constraints used by jobs such as saved-search alerts. Public
    # APIs never accept these values directly from clients.
    exclude_user_id: str | None = None
    created_after: datetime | None = None
    allow_relaxation: bool = True


@dataclass(frozen=True)
class RelaxedConstraint:
    kind: str
    value: str
    reason: str = "NO_EXACT_MATCHES"

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "value": self.value, "reason": self.reason}


@dataclass
class SearchPage:
    items: list[Any]
    total_count: int
    next_cursor: str | None
    parsed_query: ParsedMarketplaceQuery
    relaxed: list[RelaxedConstraint] = field(default_factory=list)
