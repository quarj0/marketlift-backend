from __future__ import annotations

import hashlib
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .checkout_reliability import (
    CANCELLED_PROVIDER_STATUSES,
    FAILED_PROVIDER_STATUSES,
    _create_or_get_local_checkout,
    _finalize_definitive_provider_error,
)
from .models import CommercePayment, LedgerEntry, Order, SellerPaymentAccount, Settlement
from .providers import get_commerce_provider
from .providers.base import CommerceProviderError
from .services import (
    _normalize_shipping_address,
    _scoped_checkout_idempotency_key,
    _validate_checkout_replay,
    approve_commerce_payment,
    release_due_settlements,
)


def _stripe_account_status(result: dict) -> tuple[str, bool]:
    """Translate the live Accounts v2 state into Marketlift's commerce status.

    The recipient configuration is the capability Marketlift actually depends on:
    the seller must be able to receive a Stripe transfer after delivery. We also
    require that Stripe has no currently-due or past-due onboarding requirement.
    """
    configuration = result.get("configuration") or {}
    recipient = configuration.get("recipient") or {}
    capabilities = recipient.get("capabilities") or {}
    stripe_balance = capabilities.get("stripe_balance") or {}
    stripe_transfers = stripe_balance.get("stripe_transfers") or {}
    transfer_status = str(stripe_transfers.get("status") or "").strip().lower()

    requirements = result.get("requirements") or {}
    summary = requirements.get("summary") or {}
    minimum_deadline = summary.get("minimum_deadline") or {}
    requirements_status = str(
        minimum_deadline.get("status") or ""
    ).strip().lower()

    onboarding_complete = requirements_status not in {
        "currently_due",
        "past_due",
    }
    if transfer_status == "active" and onboarding_complete:
        return SellerPaymentAccount.Status.ACTIVE, True
    if transfer_status in {"restricted", "unsupported"} or requirements_status == "past_due":
        return SellerPaymentAccount.Status.RESTRICTED, False
    return SellerPaymentAccount.Status.PENDING, False


def _stripe_account_metadata(result: dict, *, status: str) -> dict:
    configuration = result.get("configuration") or {}
    recipient = configuration.get("recipient") or {}
    capabilities = recipient.get("capabilities") or {}
    stripe_balance = capabilities.get("stripe_balance") or {}
    stripe_transfers = stripe_balance.get("stripe_transfers") or {}
    requirements = result.get("requirements") or {}
    summary = requirements.get("summary") or {}
    minimum_deadline = summary.get("minimum_deadline") or {}
    return {
        "provider_status": status,
        "stripe_transfers_status": str(
            stripe_transfers.get("status") or ""
        ).strip().lower(),
        "requirements_status": str(
            minimum_deadline.get("status") or ""
        ).strip().lower(),
        "requirements": requirements,
    }


def _mark_seller_verified_from_stripe(seller, *, active: bool) -> None:
    """Let successful Stripe KYC satisfy commerce-seller verification.

    Classified-only sellers can still use Marketlift's independent verification
    workflow. We never unset an existing verification if Stripe later requests an
    update; instead the payment capability is restricted until Stripe is current.
    """
    if active and not seller.verified:
        seller.verified_at = timezone.now()
        seller.save(update_fields=("verified_at", "updated_at"))


def _apply_stripe_account_snapshot(
    account: SellerPaymentAccount,
    result: dict,
) -> SellerPaymentAccount:
    status, payouts_enabled = _stripe_account_status(result)
    account.provider = "stripe"
    account.status = status
    # This existing field means "Marketlift can release seller proceeds to the
    # connected account". The source of truth is the live V2 transfer capability.
    account.payouts_enabled = payouts_enabled
    if payouts_enabled:
        account.kyc_url = ""
    account.metadata = _stripe_account_metadata(result, status=status)
    account.save(
        update_fields=(
            "provider",
            "status",
            "payouts_enabled",
            "kyc_url",
            "metadata",
            "updated_at",
        )
    )
    _mark_seller_verified_from_stripe(
        account.seller,
        active=status == SellerPaymentAccount.Status.ACTIVE,
    )
    return account


def sync_seller_payment_account_from_stripe(*, seller) -> SellerPaymentAccount | None:
    """Refresh seller onboarding status directly from Stripe Accounts v2.

    We keep the Stripe account ID and the last observed state in Marketlift for
    mapping/audit purposes, but callers never treat the cached status as the
    authoritative answer. This function is used by the seller payments query so
    every status view is backed by Stripe's current requirements/capabilities.
    """
    try:
        existing = SellerPaymentAccount.objects.select_related("seller").get(
            seller=seller
        )
    except SellerPaymentAccount.DoesNotExist:
        return None

    if existing.provider != "stripe" or not existing.provider_recipient_id:
        return existing

    provider = get_commerce_provider()
    if provider.code != "stripe":
        raise ValidationError("Stripe is not the active commerce provider.")

    current = provider.get_recipient(existing.provider_recipient_id)
    with transaction.atomic():
        account = (
            SellerPaymentAccount.objects.select_for_update()
            .select_related("seller")
            .get(pk=existing.pk)
        )
        return _apply_stripe_account_snapshot(account, current)


@transaction.atomic
def activate_seller_payments(
    *,
    seller,
    recipient_payload: dict | None = None,
    payout_method: str = "bank_account",
) -> SellerPaymentAccount:
    """Create or resume the seller's Stripe-hosted Connect onboarding."""
    if seller.country_code != "BR":
        raise ValidationError(
            "Stripe Connect seller payouts are currently enabled for Brazil only."
        )

    provider = get_commerce_provider()
    if provider.code != "stripe":
        raise ValidationError("Stripe Connect is not the active commerce provider.")

    account, _ = SellerPaymentAccount.objects.select_for_update().get_or_create(
        seller=seller,
        defaults={"provider": "stripe"},
    )
    account.provider = "stripe"

    if account.provider_recipient_id:
        # Always ask Stripe for the current status before deciding whether
        # onboarding is complete. Regulatory requirements can change later.
        current = provider.get_recipient(account.provider_recipient_id)
        account = _apply_stripe_account_snapshot(account, current)
        if account.status == SellerPaymentAccount.Status.ACTIVE:
            return account

        link = provider.create_kyc_link(account.provider_recipient_id)
        account.kyc_url = str(link.get("url") or "")
        account.save(update_fields=("kyc_url", "updated_at"))
        return account

    user = seller.user
    result = provider.create_recipient(
        payload={
            "country": seller.country_code,
            "email": user.email,
            "display_name": (
                seller.display_name
                or user.full_name
                or user.email
            ),
        },
        idempotency_key=f"stripe-connect-account:{seller.id}",
    )
    recipient_id = str(result.get("id") or "").strip()
    if not recipient_id:
        raise CommerceProviderError(
            "Stripe did not return a connected account id.",
            retryable=False,
        )

    account.provider_recipient_id = recipient_id
    account.payout_method = SellerPaymentAccount.PayoutMethod.BANK_ACCOUNT
    account.payout_destination_masked = "Stripe Connect"
    account.save(
        update_fields=(
            "provider",
            "provider_recipient_id",
            "payout_method",
            "payout_destination_masked",
            "updated_at",
        )
    )
    account = _apply_stripe_account_snapshot(account, result)

    if account.status != SellerPaymentAccount.Status.ACTIVE:
        link = provider.create_kyc_link(recipient_id)
        account.kyc_url = str(link.get("url") or "")
        account.save(update_fields=("kyc_url", "updated_at"))
    return account


def _stripe_checkout_payload(*, order: Order, buyer) -> dict:
    account = SellerPaymentAccount.objects.get(seller_id=order.seller_id)
    connected_account = str(account.provider_recipient_id or "").strip()
    if not connected_account or account.provider != "stripe":
        raise ValidationError("Seller Stripe Connect account is not configured.")

    items = [
        {
            "amount": order.unit_price_cents,
            "description": str(order.listing_snapshot.get("title") or "Marketlift item")[:255],
            "quantity": order.quantity,
            "code": str(order.listing_id),
        }
    ]
    if order.shipping_amount_cents:
        items.append(
            {
                "amount": order.shipping_amount_cents,
                "description": "Marketlift local delivery",
                "quantity": 1,
                "code": f"delivery:{order.id}",
            }
        )

    payment = order.payments.order_by("-created_at").first()
    frontend = settings.MARKETLIFT_FRONTEND_URL.rstrip("/")
    return {
        "code": order.reference,
        "reference": order.reference,
        "currency": order.currency,
        "payment_method": payment.method,
        "buyer_email": buyer.email,
        "items": items,
        "success_url": (
            f"{frontend}/account/orders?payment=success&session_id="
            "{CHECKOUT_SESSION_ID}"
        ),
        "cancel_url": f"{frontend}/checkout/{order.listing_id}?payment=cancelled",
        "expires_at": int(order.created_at.timestamp()) + (35 * 60),
        "seller_account_id": connected_account,
        "metadata": {
            "marketlift_order_id": str(order.id),
            "marketlift_reference": order.reference,
            "marketlift_seller_account_id": connected_account,
        },
        # Compatibility shape retained for reliability tests and provider-neutral
        # diagnostics. Stripe itself ignores this field.
        "payments": [
            {
                "payment_method": payment.method,
                "split": [
                    {
                        "amount": order.seller_proceeds_cents,
                        "recipient_id": connected_account,
                    },
                    {
                        "amount": order.total_cents - order.seller_proceeds_cents,
                        "recipient_id": "stripe_platform",
                    },
                ],
            }
        ],
    }


def _apply_stripe_checkout_result(*, payment_id, result: dict):
    with transaction.atomic():
        payment = (
            CommercePayment.objects.select_for_update()
            .select_related("order")
            .get(pk=payment_id)
        )
        order = Order.objects.select_for_update().get(pk=payment.order_id)
        if payment.status != CommercePayment.Status.PENDING:
            return order, payment

        payment.provider = "stripe"
        payment.provider_order_id = str(result.get("id") or "")
        payment.provider_transaction_id = str(result.get("payment_intent") or "")
        payment.provider_status = str(
            result.get("payment_status") or result.get("status") or ""
        )
        payment.checkout_data = {
            "checkout_url": str(result.get("checkout_url") or result.get("url") or ""),
            "expires_at": str(result.get("expires_at") or ""),
            "payment_intent": str(result.get("payment_intent") or ""),
        }

        lowered = payment.provider_status.lower()
        if lowered in CANCELLED_PROVIDER_STATUSES | FAILED_PROVIDER_STATUSES | {"expired"}:
            payment.status = (
                CommercePayment.Status.CANCELLED
                if lowered in CANCELLED_PROVIDER_STATUSES | {"expired"}
                else CommercePayment.Status.FAILED
            )
            payment.save()
            return order, payment

        payment.save()
        if lowered in {"paid", "approved", "succeeded"}:
            approve_commerce_payment(payment)
            payment.refresh_from_db()
            order.refresh_from_db()
        return order, payment


def create_checkout_order(
    *,
    buyer,
    listing_id,
    quantity: int,
    fulfillment_method: str,
    shipping_address: dict | None,
    payment_method: str,
    customer_document: str = "",
    customer_phone: str = "",
    card_id: str | None = None,
    idempotency_key: str,
):
    if quantity < 1:
        raise ValidationError({"quantity": "Quantity must be at least one."})
    if payment_method not in {CommercePayment.Method.CARD, CommercePayment.Method.PIX}:
        raise ValidationError({"paymentMethod": "Only card and Pix are supported."})

    normalized_address = _normalize_shipping_address(
        fulfillment_method, shipping_address
    )
    scoped_key = _scoped_checkout_idempotency_key(
        buyer_id=buyer.id, raw_key=idempotency_key
    )

    previous = (
        CommercePayment.objects.select_related("order")
        .filter(idempotency_key=scoped_key)
        .first()
    )
    if previous:
        _validate_checkout_replay(
            previous=previous,
            buyer=buyer,
            listing_id=listing_id,
            quantity=quantity,
            fulfillment_method=fulfillment_method,
            payment_method=payment_method,
            shipping_address=normalized_address,
        )
        return previous.order, previous

    provider = get_commerce_provider()
    if provider.code != "stripe":
        raise ValidationError("Stripe is not the active commerce provider.")

    order, payment = _create_or_get_local_checkout(
        buyer=buyer,
        listing_id=listing_id,
        quantity=quantity,
        fulfillment_method=fulfillment_method,
        normalized_address=normalized_address,
        payment_method=payment_method,
        scoped_key=scoped_key,
    )
    if payment.provider != "stripe":
        payment.provider = "stripe"
        payment.save(update_fields=("provider", "updated_at"))

    if (
        payment.status != CommercePayment.Status.PENDING
        or order.status != Order.Status.PENDING_PAYMENT
        or payment.provider_order_id
    ):
        return order, payment

    try:
        result = provider.create_order(
            payload=_stripe_checkout_payload(order=order, buyer=buyer),
            idempotency_key=scoped_key,
        )
    except CommerceProviderError as exc:
        if exc.retryable:
            raise
        return _finalize_definitive_provider_error(payment_id=payment.id, exc=exc)

    return _apply_stripe_checkout_result(payment_id=payment.id, result=result)


def _payout_batch_key(*, seller_id, settlements: list[Settlement]) -> str:
    ids = ":".join(sorted(str(row.id) for row in settlements))
    digest = hashlib.sha256(f"{seller_id}:{ids}".encode("utf-8")).hexdigest()[:40]
    return f"seller-payout:{seller_id}:{digest}"


def withdraw_available_balance(*, seller) -> dict:
    release_due_settlements(seller=seller)
    provider = get_commerce_provider()
    if provider.code != "stripe":
        raise ValidationError("Stripe is not the active commerce provider.")

    with transaction.atomic():
        account = SellerPaymentAccount.objects.select_for_update().get(seller=seller)
        if (
            account.provider != "stripe"
            or account.status != SellerPaymentAccount.Status.ACTIVE
            or not account.payouts_enabled
            or not account.provider_recipient_id
        ):
            raise ValidationError("Seller payouts are not active.")

        pending_retry = list(
            Settlement.objects.select_for_update()
            .filter(
                seller=seller,
                status=Settlement.Status.PAYOUT_REQUESTED,
                provider_transfer_id="",
            )
            .exclude(payout_idempotency_key="")
            .order_by("payout_requested_at", "created_at")
        )
        if pending_retry:
            batch_key = pending_retry[0].payout_idempotency_key
            settlements = [
                row for row in pending_retry if row.payout_idempotency_key == batch_key
            ]
        else:
            settlements = list(
                Settlement.objects.select_for_update()
                .filter(seller=seller, status=Settlement.Status.AVAILABLE)
                .order_by("created_at")
            )
            if not settlements:
                raise ValidationError("There is no available balance to withdraw.")
            batch_key = _payout_batch_key(seller_id=seller.id, settlements=settlements)
            now = timezone.now()
            for settlement in settlements:
                settlement.status = Settlement.Status.PAYOUT_REQUESTED
                settlement.payout_idempotency_key = batch_key
                settlement.payout_requested_at = now
                settlement.save(
                    update_fields=(
                        "status",
                        "payout_idempotency_key",
                        "payout_requested_at",
                        "updated_at",
                    )
                )
        amount = sum(row.amount_cents for row in settlements)
        recipient_id = account.provider_recipient_id

    try:
        transfer = provider.create_transfer(
            recipient_id=recipient_id,
            amount_cents=amount,
            idempotency_key=batch_key,
        )
    except CommerceProviderError as exc:
        if not exc.retryable:
            with transaction.atomic():
                rows = Settlement.objects.select_for_update().filter(
                    seller=seller,
                    status=Settlement.Status.PAYOUT_REQUESTED,
                    payout_idempotency_key=batch_key,
                    provider_transfer_id="",
                )
                for settlement in rows:
                    financially_blocked = (
                        settlement.order.status == Order.Status.REFUNDED
                        or settlement.order.payments.filter(
                            status=CommercePayment.Status.CHARGEBACK
                        ).exists()
                    )
                    settlement.status = (
                        Settlement.Status.BLOCKED
                        if financially_blocked
                        else Settlement.Status.AVAILABLE
                    )
                    settlement.payout_idempotency_key = ""
                    settlement.payout_requested_at = None
                    settlement.save(
                        update_fields=(
                            "status",
                            "payout_idempotency_key",
                            "payout_requested_at",
                            "updated_at",
                        )
                    )
        raise

    transfer_id = str(transfer.get("id") or "").strip()
    if not transfer_id:
        raise CommerceProviderError("Stripe did not return a transfer id.")

    with transaction.atomic():
        now = timezone.now()
        rows = list(
            Settlement.objects.select_for_update().filter(
                seller=seller,
                status=Settlement.Status.PAYOUT_REQUESTED,
                payout_idempotency_key=batch_key,
            )
        )
        for settlement in rows:
            settlement.provider_transfer_id = transfer_id
            settlement.status = Settlement.Status.PAID
            settlement.paid_at = now
            settlement.save(
                update_fields=(
                    "provider_transfer_id",
                    "status",
                    "paid_at",
                    "updated_at",
                )
            )
            LedgerEntry.objects.get_or_create(
                order=settlement.order,
                seller=seller,
                kind=LedgerEntry.Kind.SELLER_PAYOUT,
                provider_reference=transfer_id,
                defaults={
                    "amount_cents": -settlement.amount_cents,
                    "currency": settlement.order.currency,
                    "metadata": {"payout_batch_key": batch_key, "provider": "stripe"},
                },
            )
    return {
        "transfer_id": transfer_id,
        "amount_cents": amount,
        "status": str(transfer.get("status") or "succeeded"),
    }
