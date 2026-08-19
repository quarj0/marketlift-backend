import strawberry


@strawberry.input
class PaymentPayerInput:
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    identification_type: str | None = None
    identification_number: str | None = None
    zip_code: str | None = None
    street_name: str | None = None
    street_number: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    state: str | None = None


@strawberry.input
class CardPaymentInput:
    token: str
    payment_method_id: str
    payment_type: str = "credit_card"
    installments: int = 1
