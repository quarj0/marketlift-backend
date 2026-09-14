from __future__ import annotations

from abc import ABC, abstractmethod


class CommerceProviderError(RuntimeError):
    pass


class CommerceProvider(ABC):
    code: str

    @abstractmethod
    def create_recipient(self, *, payload: dict, idempotency_key: str) -> dict: ...

    @abstractmethod
    def create_kyc_link(self, recipient_id: str) -> dict: ...

    @abstractmethod
    def create_order(self, *, payload: dict, idempotency_key: str) -> dict: ...

    @abstractmethod
    def get_recipient_balance(self, recipient_id: str) -> dict: ...

    @abstractmethod
    def create_transfer(
        self, *, recipient_id: str, amount_cents: int, idempotency_key: str
    ) -> dict: ...

    @abstractmethod
    def cancel_charge(self, charge_id: str, *, amount_cents: int | None = None) -> dict: ...
