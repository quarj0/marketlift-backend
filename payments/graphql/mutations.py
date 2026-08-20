import strawberry
from dataclasses import asdict
from django.core.exceptions import ValidationError

from listings.models import Listing
from marketlift.graphql.auth import request_from_info, require_seller
from marketlift.graphql.errors import not_found_error, validation_error
from payments.models import Payment
from payments.services import (
    create_promotion_payment,
    create_subscription_payment,
    refresh_payment,
)
from promotions.models import PromotionProduct
from subscriptions.models import SellerPlan
from .inputs import CardPaymentInput, PaymentPayerInput
from .mappers import payment_to_type
from .types import PaymentType


def _dict(value):
    if value is None:
        return None
    return {key: val for key, val in asdict(value).items() if val is not None}


@strawberry.type
class PaymentMutation:
    @strawberry.mutation
    def create_subscription_payment(
        self,
        info: strawberry.Info,
        plan_id: str,
        billing_cycle: str,
        method: str,
        idempotency_key: str,
        payer: PaymentPayerInput | None = None,
        card: CardPaymentInput | None = None,
    ) -> PaymentType:
        seller = require_seller(info)
        try:
            plan = SellerPlan.objects.get(code=plan_id, active=True)
        except SellerPlan.DoesNotExist as exc:
            raise not_found_error("Seller plan", code="SELLER_PLAN_NOT_FOUND") from exc
        try:
            p = create_subscription_payment(
                seller=seller,
                plan=plan,
                billing_cycle=billing_cycle,
                method=method,
                idempotency_key=idempotency_key,
                payer=_dict(payer),
                card=_dict(card),
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(exc, code="PAYMENT_VALIDATION_ERROR") from exc
        return payment_to_type(p)

    @strawberry.mutation
    def create_promotion_payment(
        self,
        info: strawberry.Info,
        listing_id: strawberry.ID,
        promotion_id: str,
        method: str,
        idempotency_key: str,
        payer: PaymentPayerInput | None = None,
        card: CardPaymentInput | None = None,
    ) -> PaymentType:
        seller = require_seller(info)
        try:
            listing = Listing.objects.get(pk=str(listing_id))
            product = PromotionProduct.objects.get(code=promotion_id, active=True)
        except (Listing.DoesNotExist, PromotionProduct.DoesNotExist, ValueError) as exc:
            raise not_found_error(
                "Listing or promotion", code="PAYMENT_TARGET_NOT_FOUND"
            ) from exc
        try:
            p = create_promotion_payment(
                seller=seller,
                listing=listing,
                product=product,
                method=method,
                idempotency_key=idempotency_key,
                payer=_dict(payer),
                card=_dict(card),
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(exc, code="PAYMENT_VALIDATION_ERROR") from exc
        return payment_to_type(p)

    @strawberry.mutation
    def refresh_payment(self, info: strawberry.Info, id: strawberry.ID) -> PaymentType:
        seller = require_seller(info)
        try:
            p = Payment.objects.select_related(
                "seller", "seller_plan", "listing", "promotion_product"
            ).get(pk=str(id), seller=seller)
        except (Payment.DoesNotExist, ValueError) as exc:
            raise not_found_error("Payment", code="PAYMENT_NOT_FOUND") from exc
        try:
            p = refresh_payment(payment=p, request=request_from_info(info))
        except ValidationError as exc:
            raise validation_error(exc, code="PAYMENT_VALIDATION_ERROR") from exc
        return payment_to_type(p)
