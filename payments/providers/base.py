from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass
class ProviderResult:
    order_id: str
    payment_id: str = ""
    status: str = "created"
    status_detail: str = ""
    checkout_data: dict[str, Any] = field(default_factory=dict)


class PaymentProviderError(Exception):
    pass


class BasePaymentProvider:
    name = "base"

    def create_order(
        self, *, payment, payer: dict, card: dict | None = None
    ) -> ProviderResult:
        raise NotImplementedError

    def get_order(self, order_id: str) -> ProviderResult:
        raise NotImplementedError
