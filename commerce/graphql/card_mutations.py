import strawberry
from django.core.exceptions import ValidationError

from marketlift.graphql.auth import require_user
from marketlift.graphql.errors import domain_error, validation_error

from commerce.providers import get_commerce_provider
from commerce.providers.base import CommerceProviderError


def _customer_payload(user, document: str, phone: str) -> dict:
    document_digits = "".join(ch for ch in document if ch.isdigit())
    if len(document_digits) not in {11, 14}:
        raise ValidationError({"document": "Enter a valid CPF or CNPJ."})
    phone_digits = "".join(ch for ch in phone if ch.isdigit())
    if phone_digits.startswith("55") and len(phone_digits) > 11:
        phone_digits = phone_digits[2:]
    if len(phone_digits) not in {10, 11}:
        raise ValidationError({"phone": "Enter a valid Brazilian mobile number."})
    return {
        "name": user.full_name or user.email,
        "email": user.email,
        "code": f"marketlift-user-{user.id}",
        "document": document_digits,
        "document_type": "CNPJ" if len(document_digits) == 14 else "CPF",
        "type": "company" if len(document_digits) == 14 else "individual",
        "phones": {
            "mobile_phone": {
                "country_code": "55",
                "area_code": phone_digits[:2],
                "number": phone_digits[2:],
            }
        },
    }


@strawberry.type
class CommerceCardMutation:
    @strawberry.mutation
    def vault_commerce_card(
        self,
        info: strawberry.Info,
        card_token: str,
        customer_document: str,
        customer_phone: str,
    ) -> str:
        user = require_user(info)
        token = card_token.strip()
        if not token.startswith("token_"):
            raise validation_error(
                ValidationError({"cardToken": "Invalid Pagar.me card token."}),
                code="CARD_TOKEN_INVALID",
            )
        provider = get_commerce_provider()
        try:
            customer = provider.create_customer(
                payload=_customer_payload(user, customer_document, customer_phone),
                idempotency_key=f"buyer-customer:{user.id}",
            )
            customer_id = str(customer.get("id") or "")
            if not customer_id:
                raise CommerceProviderError("Pagar.me did not return a customer id.")
            card = provider.create_card(
                customer_id=customer_id,
                token=token,
                idempotency_key=f"buyer-card:{user.id}:{token}",
            )
        except ValidationError as exc:
            raise validation_error(exc, code="CARD_VAULT_VALIDATION_ERROR") from exc
        except CommerceProviderError as exc:
            raise domain_error(
                str(exc), code="PAYMENT_PROVIDER_ERROR", status=502
            ) from exc
        card_id = str(card.get("id") or "")
        if not card_id:
            raise domain_error(
                "Pagar.me did not return a card id.",
                code="PAYMENT_PROVIDER_ERROR",
                status=502,
            )
        return card_id
