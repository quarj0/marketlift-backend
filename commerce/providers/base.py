from __future__ import annotations

from abc import ABC, abstractmethod


class CommerceProviderError(RuntimeError):
    """Provider failure with enough metadata to make retry decisions safely.

    ``retryable`` means the caller cannot know whether the provider accepted the
    request (transport errors, rate limits, and server errors). In that case an
    idempotent retry must reuse the exact same operation key. Client/request
    validation failures are definitive and can release any local reservation.
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = True,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class CommerceProvider(ABC):
    code: str

    @abstractmethod
    def create_recipient(self, *, payload: dict, idempotency_key: str) -> dict: ...

    @abstractmethod
    def create_kyc_link(self, recipient_id: str) -> dict: ...

    @abstractmethod
    def create_customer(self, *, payload: dict, idempotency_key: str) -> dict: ...

    @abstractmethod
    def create_card(
        self, *, customer_id: str, token: str, idempotency_key: str
    ) -> dict: ...

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