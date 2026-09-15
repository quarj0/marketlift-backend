from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from categories.models import Category
from listings.models import Listing

from .models import (
    CommercePayment,
    Dispute,
    LedgerEntry,
    Order,
    SellerPaymentAccount,
    Settlement,
    Shipment,
)
from .policy_models import CategoryCommercePolicy, ListingCommerceSettings
from .providers import get_commerce_provider
from .providers.base import CommerceProviderError


@dataclass(frozen=True)
class ResolvedCommercePolicy:
    mode: str = CategoryCommercePolicy.Mode.DISABLED
    requires_verified_seller: bool = True
    max_checkout_value_cents: int | None = None
    shipping_allowed: bool = False
    local_delivery_allowed: bool = False
    pickup_allowed: bool = True
    source_category_id: str | None = None


def money_to_cents(value: Decimal) -> int:
    return int((value * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def resolve_category_policy(category: Category | None) -> ResolvedCommercePolicy:
    current = category
    while current is not None:
        try:
            row = current.commerce_policy
        except CategoryCommercePolicy.DoesNotExist:
            row = None
        if row is not None:
            return ResolvedCommercePolicy(
                mode=row.mode,
                requires_verified_seller=row.requires_verified_seller,
                max_checkout_value_cents=row.max_checkout_value_cents,
                shipping_allowed=row.shipping_allowed,
                local_delivery_allowed=row.local_delivery_allowed,
                pickup_allowed=row.pickup_allowed,
                source_category_id=str(current.id),
            )
        current = current.parent
    return ResolvedCommercePolicy()


def _payment_account_for_seller(seller) -> SellerPaymentAccount | None:
    try:
        return seller.payment_account
    except SellerPaymentAccount.DoesNotExist:
        return None


def listing_commerce_state(listing: Listing) -> dict:
    policy = resolve_category_policy(listing.category)
    try:
        config = listing.commerce_settings
    except ListingCommerceSettings.DoesNotExist:
        config = None
    account = _payment_account_for_seller(listing.seller)

    reasons: list[str] = []
    if policy.mode == CategoryCommercePolicy.Mode.DISABLED:
        reasons.append("category_classified_only")
    if config is None or not config.checkout_enabled:
        reasons.append("seller_checkout_disabled")
    if policy.requires_verified_seller and not listing.seller.verified:
        reasons.append("seller_not_verified")
    if account is None or account.status != SellerPaymentAccount.Status.ACTIVE:
        reasons.append("seller_payments_not_active")
    elif not account.payouts_enabled or not account.provider_recipient_id:
        reasons.append("seller_payouts_not_enabled")
    if listing.price is None or listing.price <= 0:
        reasons.append("price_required")
    if (
        listing.price is not None
        and policy.max_checkout_value_cents is not None
        and money_to_cents(listing.price) > policy.max_checkout_value_cents
    ):
        reasons.append("price_above_checkout_limit")
    if config is not None and config.stock_quantity < 1:
        reasons.append("out_of_stock")

    is_public = (
        listing.status == Listing.Status.PUBLISHED
        and not listing.seller.is_suspended
        and listing.seller.user.is_active
        and listing.category_id is not None
        and listing.category.active
        and listing.seller_deleted_at is None
    )
    if not is_public:
        reasons.append("listing_unavailable")

    methods: list[str] = []
    if config is not None:
        if config.shipping_enabled and policy.shipping_allowed:
            methods.append(Order.FulfillmentMethod.SHIPPING)
        if config.local_delivery_enabled and policy.local_delivery_allowed:
            methods.append(Order.FulfillmentMethod.LOCAL_DELIVERY)
        if config.pickup_enabled and policy.pickup_allowed:
            methods.append(Order.FulfillmentMethod.PICKUP)
    if not methods and policy.mode != CategoryCommercePolicy.Mode.DISABLED:
        reasons.append("no_fulfillment_method")

    return {
        "mode": policy.mode,
        "checkout_enabled": not reasons,
        "inspection_allowed": policy.mode
        in {
            CategoryCommercePolicy.Mode.OPTIONAL,
            CategoryCommercePolicy.Mode.DISABLED,
        },
        "stock_quantity": config.stock_quantity if config else 0,
        "fulfillment_methods": methods,
        "reasons": reasons,
        "requires_verified_seller": policy.requires_verified_seller,
        "max_checkout_value_cents": policy.max_checkout_value_cents,
    }


@transaction.atomic
def set_category_commerce_policy(
    *,
    category: Category,
    mode: str,
    requires_verified_seller: bool,
    max_checkout_value_cents: int | None,
    shipping_allowed: bool,
    local_delivery_allowed: bool,
    pickup_allowed: bool,
) -> CategoryCommercePolicy:
    if mode not in CategoryCommercePolicy.Mode.values:
        raise ValidationError({"mode": "Unsupported commerce mode."})
    if max_checkout_value_cents is not None and max_checkout_value_cents <= 0:
        raise ValidationError(
            {"maxCheckoutValueCents": "Maximum value must be positive."}
        )
    policy, _ = CategoryCommercePolicy.objects.update_or_create(
        category=category,
        defaults={
            "mode": mode,
            "requires_verified_seller": requires_verified_seller,
            "max_checkout_value_cents": max_checkout_value_cents,
            "shipping_allowed": shipping_allowed,
            "local_delivery_allowed": local_delivery_allowed,
            "pickup_allowed": pickup_allowed,
        },
    )
    if mode == CategoryCommercePolicy.Mode.DISABLED:
        ListingCommerceSettings.objects.filter(
            listing__category=category, checkout_enabled=True
        ).update(checkout_enabled=False)
    return policy


@transaction.atomic
def configure_listing_commerce(
    *,
    listing: Listing,
    checkout_enabled: bool,
    stock_quantity: int,
    shipping_enabled: bool,
    local_delivery_enabled: bool,
    pickup_enabled: bool,
    package_weight_grams: int | None = None,
    package_length_cm: int | None = None,
    package_width_cm: int | None = None,
    package_height_cm: int | None = None,
) -> ListingCommerceSettings:
    policy = resolve_category_policy(listing.category)
    if checkout_enabled and policy.mode == CategoryCommercePolicy.Mode.DISABLED:
        raise ValidationError("Checkout is disabled for this category.")
    if (
        checkout_enabled
        and policy.requires_verified_seller
        and not listing.seller.verified
    ):
        raise ValidationError("Seller verification is required for online checkout.")
    if checkout_enabled and (listing.price is None or listing.price <= 0):
        raise ValidationError("A fixed positive price is required for online checkout.")
    if checkout_enabled and policy.max_checkout_value_cents is not None:
        if money_to_cents(listing.price) > policy.max_checkout_value_cents:
            raise ValidationError("This listing is above the category checkout limit.")
    if stock_quantity < 0:
        raise ValidationError({"stockQuantity": "Stock cannot be negative."})
    if shipping_enabled and not policy.shipping_allowed:
        raise ValidationError("Shipping is not allowed for this category.")
    if local_delivery_enabled and not policy.local_delivery_allowed:
        raise ValidationError("Local delivery is not allowed for this category.")
    if pickup_enabled and not policy.pickup_allowed:
        raise ValidationError("Pickup is not allowed for this category.")
    if checkout_enabled and not any(
        (shipping_enabled, local_delivery_enabled, pickup_enabled)
    ):
        raise ValidationError("Enable at least one fulfillment method for checkout.")

    config, _ = ListingCommerceSettings.objects.update_or_create(
        listing=listing,
        defaults={
            "checkout_enabled": checkout_enabled,
            "stock_quantity": stock_quantity,
            "shipping_enabled": shipping_enabled,
            "local_delivery_enabled": local_delivery_enabled,
            "pickup_enabled": pickup_enabled,
            "package_weight_grams": package_weight_grams,
            "package_length_cm": package_length_cm,
            "package_width_cm": package_width_cm,
            "package_height_cm": package_height_cm,
        },
    )
    return config


def _masked_payout_destination(payload: dict, payout_method: str) -> str:
    if payout_method == SellerPaymentAccount.PayoutMethod.PIX:
        raw = str(payload.get("pix_key") or payload.get("pixKey") or "").strip()
        if not raw:
            return "Pix"
        return f"Pix •••• {raw[-4:]}"
    bank = payload.get("default_bank_account") or {}
    account = str(bank.get("account_number") or "")
    bank_name = str(bank.get("bank") or bank.get("bank_name") or "Bank").strip()
    return f"{bank_name} •••• {account[-4:]}" if account else bank_name


@transaction.atomic
def activate_seller_payments(
    *, seller, recipient_payload: dict, payout_method: str
) -> SellerPaymentAccount:
    if seller.country_code != "BR":
        raise ValidationError(
            "Pagar.me seller payouts are currently enabled for Brazil only."
        )
    if payout_method not in SellerPaymentAccount.PayoutMethod.values:
        raise ValidationError({"payoutMethod": "Unsupported payout method."})
    if not isinstance(recipient_payload, dict):
        raise ValidationError({"recipient": "Recipient details are required."})

    payload = dict(recipient_payload)
    payload["code"] = payload.get("code") or f"marketlift-{seller.id}"
    transfer_settings = dict(payload.get("transfer_settings") or {})
    transfer_settings["transfer_enabled"] = False
    payload["transfer_settings"] = transfer_settings

    account, _ = SellerPaymentAccount.objects.select_for_update().get_or_create(
        seller=seller
    )
    if account.provider_recipient_id:
        return account

    provider = get_commerce_provider()
    key = f"seller-recipient:{seller.id}"
    result = provider.create_recipient(payload=payload, idempotency_key=key)
    recipient_id = str(result.get("id") or "").strip()
    if not recipient_id:
        raise CommerceProviderError("Pagar.me did not return a recipient id.")

    kyc = provider.create_kyc_link(recipient_id)
    kyc_url = str(kyc.get("url") or kyc.get("kyc_url") or "")
    provider_status = str(result.get("status") or "").lower()
    active = provider_status in {"active", "enabled", "registered"}
    account.provider_recipient_id = recipient_id
    account.status = (
        SellerPaymentAccount.Status.ACTIVE
        if active
        else SellerPaymentAccount.Status.PENDING
    )
    account.payout_method = payout_method
    account.payout_destination_masked = _masked_payout_destination(
        payload, payout_method
    )
    account.payouts_enabled = active
    account.kyc_url = kyc_url
    account.metadata = {
        "provider_status": provider_status,
        "recipient_code": result.get("code"),
    }
    account.save()
    return account


def _snapshot_listing(listing: Listing) -> dict:
    attrs = {}
    for row in listing.attribute_values.all():
        value = row.value
        attrs[row.key] = float(value) if isinstance(value, Decimal) else value
    return {
        "listing_id": str(listing.id),
        "slug": listing.slug,
        "title": listing.title,
        "description": listing.description,
        "price_cents": money_to_cents(listing.price or Decimal("0")),
        "condition": listing.condition,
        "category": listing.category_slug,
        "category_name": listing.category_name,
        "images": [media.content_url for media in listing.media.all()],
        "attributes": attrs,
        "seller_id": str(listing.seller_id),
        "seller_name": str(listing.seller),
    }


def _buyer_customer_payload(*, buyer, document: str, phone: str) -> dict:
    digits = "".join(ch for ch in document if ch.isdigit())
    if len(digits) not in {11, 14}:
        raise ValidationError({"document": "Enter a valid CPF or CNPJ."})
    phone_digits = "".join(ch for ch in phone if ch.isdigit())
    if phone_digits.startswith("55") and len(phone_digits) > 11:
        phone_digits = phone_digits[2:]
    if len(phone_digits) not in {10, 11}:
        raise ValidationError({"phone": "Enter a valid Brazilian mobile number."})
    return {
        "name": buyer.full_name or buyer.email,
        "email": buyer.email,
        "type": "company" if len(digits) == 14 else "individual",
        "document": digits,
        "phones": {
            "mobile_phone": {
                "country_code": "55",
                "area_code": phone_digits[:2],
                "number": phone_digits[2:],
            }
        },
    }


def _payment_payload(*, method: str, card_id: str | None, split: list[dict]) -> dict:
    if method == CommercePayment.Method.PIX:
        return {
            "payment_method": "pix",
            "pix": {
                "expires_in": int(
                    getattr(settings, "PAGARME_PIX_EXPIRES_SECONDS", 1800)
                )
            },
            "split": split,
        }
    if method == CommercePayment.Method.CARD:
        if not card_id:
            raise ValidationError({"cardId": "A tokenized card id is required."})
        return {
            "payment_method": "credit_card",
            "credit_card": {
                "installments": 1,
                "statement_descriptor": getattr(
                    settings, "PAGARME_STATEMENT_DESCRIPTOR", "MARKETLIFT"
                )[:13],
                "card_id": card_id,
            },
            "split": split,
        }
    raise ValidationError({"method": "Only Pix and card are supported."})


def _checkout_data(result: dict) -> dict:
    charges = result.get("charges") or []
    charge = charges[0] if charges else {}
    tx = charge.get("last_transaction") or {}
    return {
        "qr_code": tx.get("qr_code") or "",
        "qr_code_url": tx.get("qr_code_url") or "",
        "expires_at": tx.get("expires_at") or "",
        "provider_charge_id": charge.get("id") or "",
    }


def _scoped_checkout_idempotency_key(*, buyer_id, raw_key: str) -> str:
    clean = str(raw_key or "").strip()
    if not clean:
        raise ValidationError({"idempotencyKey": "An idempotency key is required."})
    digest = hashlib.sha256(f"{buyer_id}:{clean}".encode("utf-8")).hexdigest()
    return f"checkout:{digest}"


def _normalize_shipping_address(
    fulfillment_method: str, shipping_address: dict | None
) -> dict:
    if fulfillment_method == Order.FulfillmentMethod.PICKUP:
        return {}
    if fulfillment_method not in {
        Order.FulfillmentMethod.SHIPPING,
        Order.FulfillmentMethod.LOCAL_DELIVERY,
    }:
        raise ValidationError({"fulfillmentMethod": "Unsupported fulfillment method."})
    if not isinstance(shipping_address, dict):
        raise ValidationError({"shippingAddress": "A delivery address is required."})

    required = ("street", "number", "district", "city", "state", "zipCode")
    cleaned = {key: str(shipping_address.get(key) or "").strip() for key in required}
    missing = [key for key, value in cleaned.items() if not value]
    if missing:
        raise ValidationError(
            {
                "shippingAddress": (
                    "Complete the delivery address before paying. Missing: "
                    + ", ".join(missing)
                )
            }
        )

    cleaned["state"] = cleaned["state"].upper()
    if len(cleaned["state"]) != 2:
        raise ValidationError(
            {"shippingAddress": "State must be a two-letter UF code."}
        )
    zip_digits = "".join(ch for ch in cleaned["zipCode"] if ch.isdigit())
    if len(zip_digits) != 8:
        raise ValidationError({"shippingAddress": "Enter a valid eight-digit CEP."})
    cleaned["zipCode"] = zip_digits
    country = str(shipping_address.get("country") or "BR").strip().upper()
    if country != "BR":
        raise ValidationError(
            {"shippingAddress": "Commerce delivery is currently Brazil-only."}
        )
    cleaned["country"] = "BR"
    complement = str(shipping_address.get("complement") or "").strip()
    if complement:
        cleaned["complement"] = complement
    return cleaned


def _validate_checkout_replay(
    *,
    previous: CommercePayment,
    buyer,
    listing_id,
    quantity: int,
    fulfillment_method: str,
    payment_method: str,
    shipping_address: dict,
) -> None:
    order = previous.order
    matches = (
        order.buyer_id == buyer.id
        and str(order.listing_id) == str(listing_id)
        and order.quantity == quantity
        and order.fulfillment_method == fulfillment_method
        and previous.method == payment_method
        and order.shipping_address == shipping_address
    )
    if not matches:
        raise ValidationError(
            {
                "idempotencyKey": (
                    "This idempotency key was already used for different checkout parameters."
                )
            }
        )


@transaction.atomic
def create_checkout_order(
    *,
    buyer,
    listing_id,
    quantity: int,
    fulfillment_method: str,
    shipping_address: dict | None,
    payment_method: str,
    customer_document: str,
    customer_phone: str,
    card_id: str | None,
    idempotency_key: str,
) -> tuple[Order, CommercePayment]:
    if quantity < 1:
        raise ValidationError({"quantity": "Quantity must be at least one."})
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

    try:
        listing = (
            Listing.objects.select_for_update()
            .select_related("seller", "seller__user", "category", "category__parent")
            .prefetch_related("media", "attribute_values")
            .get(pk=str(listing_id))
        )
    except (Listing.DoesNotExist, ValueError) as exc:
        raise ValidationError({"listingId": "Listing was not found."}) from exc

    if listing.seller.user_id == buyer.id:
        raise ValidationError("You cannot buy your own listing.")
    state = listing_commerce_state(listing)
    if not state["checkout_enabled"]:
        raise ValidationError(
            {"checkout": "Online checkout is unavailable for this listing."}
        )
    if fulfillment_method not in state["fulfillment_methods"]:
        raise ValidationError(
            {"fulfillmentMethod": "This delivery method is unavailable."}
        )

    config = ListingCommerceSettings.objects.select_for_update().get(listing=listing)
    if config.stock_quantity < quantity:
        raise ValidationError({"quantity": "Not enough stock is available."})
    account = SellerPaymentAccount.objects.select_for_update().get(
        seller=listing.seller
    )

    unit_price_cents = money_to_cents(listing.price)
    subtotal_cents = unit_price_cents * quantity
    max_checkout_value_cents = state["max_checkout_value_cents"]
    if (
        max_checkout_value_cents is not None
        and subtotal_cents > max_checkout_value_cents
    ):
        raise ValidationError(
            {"quantity": "This quantity exceeds the category checkout-value limit."}
        )

    fee_bps = int(getattr(settings, "MARKETLIFT_COMMERCE_FEE_BPS", 500))
    marketplace_fee_cents = subtotal_cents * fee_bps // 10000
    if fulfillment_method == Order.FulfillmentMethod.LOCAL_DELIVERY:
        shipping_amount_cents = int(
            getattr(settings, "MARKETLIFT_LOCAL_DELIVERY_FEE_CENTS", 0)
        )
    else:
        shipping_amount_cents = 0
    total_cents = subtotal_cents + shipping_amount_cents
    seller_proceeds_cents = subtotal_cents - marketplace_fee_cents

    reference = f"ML-{uuid.uuid4().hex[:12].upper()}"
    order = Order.objects.create(
        reference=reference,
        buyer=buyer,
        seller=listing.seller,
        listing=listing,
        fulfillment_method=fulfillment_method,
        quantity=quantity,
        unit_price_cents=unit_price_cents,
        subtotal_cents=subtotal_cents,
        shipping_amount_cents=shipping_amount_cents,
        total_cents=total_cents,
        marketplace_fee_cents=marketplace_fee_cents,
        seller_proceeds_cents=seller_proceeds_cents,
        currency="BRL",
        shipping_address=normalized_address,
        listing_snapshot=_snapshot_listing(listing),
    )
    shipment = Shipment.objects.create(order=order)
    if fulfillment_method == Order.FulfillmentMethod.LOCAL_DELIVERY:
        pin = f"{secrets.randbelow(900000) + 100000:06d}"
        shipment.delivery_pin_hash = make_password(pin)
        shipment.proof = {"delivery_pin_issued": True}
        shipment.save(update_fields=("delivery_pin_hash", "proof", "updated_at"))
        order.listing_snapshot["delivery_pin"] = pin
        order.save(update_fields=("listing_snapshot", "updated_at"))

    Settlement.objects.create(
        order=order,
        seller=listing.seller,
        amount_cents=seller_proceeds_cents,
    )
    payment = CommercePayment.objects.create(
        order=order,
        method=payment_method,
        amount_cents=total_cents,
        idempotency_key=scoped_key,
    )

    marketplace_recipient = getattr(
        settings, "PAGARME_MARKETPLACE_RECIPIENT_ID", ""
    ).strip()
    if not marketplace_recipient:
        raise ValidationError("Marketplace recipient is not configured.")

    split = [
        {
            "amount": seller_proceeds_cents,
            "recipient_id": account.provider_recipient_id,
            "type": "flat",
            "options": {
                "charge_processing_fee": False,
                "charge_remainder_fee": False,
                "liable": False,
            },
        },
        {
            "amount": total_cents - seller_proceeds_cents,
            "recipient_id": marketplace_recipient,
            "type": "flat",
            "options": {
                "charge_processing_fee": True,
                "charge_remainder_fee": True,
                "liable": True,
            },
        },
    ]
    provider_payload = {
        "code": reference,
        "items": [
            {
                "amount": unit_price_cents,
                "description": listing.title[:255],
                "quantity": quantity,
                "code": str(listing.id),
            }
        ],
        "customer": _buyer_customer_payload(
            buyer=buyer, document=customer_document, phone=customer_phone
        ),
        "payments": [
            _payment_payload(method=payment_method, card_id=card_id, split=split)
        ],
        "metadata": {
            "marketlift_order_id": str(order.id),
            "marketlift_reference": reference,
        },
    }
    provider = get_commerce_provider()
    result = provider.create_order(payload=provider_payload, idempotency_key=scoped_key)
    payment.provider_order_id = str(result.get("id") or "")
    charges = result.get("charges") or []
    charge = charges[0] if charges else {}
    payment.provider_charge_id = str(charge.get("id") or "")
    last_tx = charge.get("last_transaction") or {}
    payment.provider_transaction_id = str(last_tx.get("id") or "")
    payment.provider_status = str(charge.get("status") or result.get("status") or "")
    payment.checkout_data = _checkout_data(result)

    provider_status = payment.provider_status.lower()
    cancelled_statuses = {"canceled", "cancelled"}
    failed_statuses = {
        "failed",
        "refused",
        "declined",
        "not_authorized",
        "not_authorised",
    }
    if provider_status in cancelled_statuses | failed_statuses:
        payment.status = (
            CommercePayment.Status.CANCELLED
            if provider_status in cancelled_statuses
            else CommercePayment.Status.FAILED
        )
        payment.failure_message = str(last_tx.get("acquirer_message") or "")
        payment.save()
        order.status = Order.Status.CANCELLED
        order.cancelled_at = timezone.now()
        order.save(update_fields=("status", "cancelled_at", "updated_at"))
        return order, payment

    payment.save()
    config.stock_quantity -= quantity
    config.save(update_fields=("stock_quantity", "updated_at"))

    if provider_status in {"paid", "approved"}:
        approve_commerce_payment(payment)
    return order, payment


@transaction.atomic
def approve_commerce_payment(payment: CommercePayment) -> CommercePayment:
    payment = (
        CommercePayment.objects.select_for_update()
        .select_related("order")
        .get(pk=payment.pk)
    )
    if payment.status == CommercePayment.Status.APPROVED:
        return payment
    if payment.status in {
        CommercePayment.Status.REFUNDED,
        CommercePayment.Status.CHARGEBACK,
        CommercePayment.Status.CANCELLED,
    }:
        raise ValidationError("A terminal payment cannot be approved.")
    now = timezone.now()
    payment.status = CommercePayment.Status.APPROVED
    payment.paid_at = now
    payment.save(update_fields=("status", "paid_at", "updated_at"))
    order = payment.order
    if order.status == Order.Status.CANCELLED:
        raise ValidationError("A cancelled order cannot be approved.")
    order.status = Order.Status.AWAITING_SELLER
    order.paid_at = now
    order.save(update_fields=("status", "paid_at", "updated_at"))
    settlement = Settlement.objects.select_for_update().get(order=order)
    settlement.status = Settlement.Status.HELD
    settlement.save(update_fields=("status", "updated_at"))
    if not order.ledger_entries.filter(kind=LedgerEntry.Kind.ORDER_PAYMENT).exists():
        LedgerEntry.objects.bulk_create(
            [
                LedgerEntry(
                    order=order,
                    seller=order.seller,
                    kind=LedgerEntry.Kind.ORDER_PAYMENT,
                    amount_cents=order.total_cents,
                    currency=order.currency,
                    provider_reference=payment.provider_charge_id,
                ),
                LedgerEntry(
                    order=order,
                    seller=order.seller,
                    kind=LedgerEntry.Kind.MARKETPLACE_FEE,
                    amount_cents=-order.marketplace_fee_cents,
                    currency=order.currency,
                    provider_reference=payment.provider_charge_id,
                ),
                LedgerEntry(
                    order=order,
                    seller=order.seller,
                    kind=LedgerEntry.Kind.SELLER_RECEIVABLE,
                    amount_cents=order.seller_proceeds_cents,
                    currency=order.currency,
                    provider_reference=payment.provider_charge_id,
                ),
            ]
        )
    return payment


@transaction.atomic
def mark_order_processing(*, order: Order, seller) -> Order:
    order = Order.objects.select_for_update().get(pk=order.pk, seller=seller)
    if order.status not in {Order.Status.AWAITING_SELLER, Order.Status.PAID}:
        raise ValidationError("This order cannot be moved to processing.")
    order.status = Order.Status.PROCESSING
    order.save(update_fields=("status", "updated_at"))
    return order


@transaction.atomic
def mark_order_shipped(
    *, order: Order, seller, carrier: str = "", tracking_code: str = ""
) -> Order:
    order = Order.objects.select_for_update().get(pk=order.pk, seller=seller)
    if order.status not in {Order.Status.AWAITING_SELLER, Order.Status.PROCESSING}:
        raise ValidationError("This order cannot be marked shipped.")
    shipment = Shipment.objects.select_for_update().get(order=order)
    now = timezone.now()
    order.status = Order.Status.SHIPPED
    order.shipped_at = now
    order.save(update_fields=("status", "shipped_at", "updated_at"))
    shipment.status = Shipment.Status.SHIPPED
    shipment.carrier = carrier.strip()
    shipment.tracking_code = tracking_code.strip()
    shipment.save(update_fields=("status", "carrier", "tracking_code", "updated_at"))
    return order


@transaction.atomic
def confirm_order_delivered(
    *,
    order: Order,
    buyer=None,
    delivery_pin: str | None = None,
    proof: dict | None = None,
) -> Order:
    order = Order.objects.select_for_update().get(pk=order.pk)
    if buyer is not None and order.buyer_id != buyer.id:
        raise ValidationError("Only this order's buyer can confirm delivery.")
    allowed_statuses = {
        Order.Status.AWAITING_SELLER,
        Order.Status.PROCESSING,
        Order.Status.SHIPPED,
        Order.Status.OUT_FOR_DELIVERY,
    }
    if order.paid_at is None or order.status not in allowed_statuses:
        raise ValidationError(
            "Only a paid order in fulfillment can be confirmed delivered."
        )
    shipment = Shipment.objects.select_for_update().get(order=order)
    if delivery_pin is not None:
        if not shipment.delivery_pin_hash or not check_password(
            delivery_pin, shipment.delivery_pin_hash
        ):
            raise ValidationError({"deliveryPin": "Invalid delivery code."})
    now = timezone.now()
    shipment.status = Shipment.Status.DELIVERED
    shipment.delivered_at = now
    shipment.proof = {**shipment.proof, **(proof or {})}
    shipment.save(update_fields=("status", "delivered_at", "proof", "updated_at"))
    order.status = Order.Status.DELIVERED
    order.delivered_at = now
    order.save(update_fields=("status", "delivered_at", "updated_at"))
    settlement = Settlement.objects.select_for_update().get(order=order)
    hours = int(getattr(settings, "MARKETLIFT_BUYER_PROTECTION_HOURS", 48))
    settlement.status = Settlement.Status.HELD
    settlement.release_after = now + timedelta(hours=hours)
    settlement.save(update_fields=("status", "release_after", "updated_at"))
    return order


@transaction.atomic
def open_order_dispute(*, order: Order, user, reason: str, description: str) -> Dispute:
    order = Order.objects.select_for_update().get(pk=order.pk)
    if user.id not in {order.buyer_id, order.seller.user_id}:
        raise ValidationError("You are not part of this order.")
    if order.status in {
        Order.Status.COMPLETED,
        Order.Status.CANCELLED,
        Order.Status.REFUNDED,
    }:
        raise ValidationError("This order can no longer be disputed.")
    existing = order.disputes.filter(status=Dispute.Status.OPEN).first()
    if existing:
        return existing
    dispute = Dispute.objects.create(
        order=order,
        opened_by=user,
        reason=reason.strip()[:80],
        description=description.strip(),
    )
    order.status = Order.Status.DISPUTED
    order.save(update_fields=("status", "updated_at"))
    settlement = Settlement.objects.select_for_update().get(order=order)
    settlement.status = Settlement.Status.BLOCKED
    settlement.save(update_fields=("status", "updated_at"))
    return dispute


@transaction.atomic
def release_due_settlements(*, seller=None) -> int:
    qs = Settlement.objects.select_for_update().select_related("order")
    qs = qs.filter(
        status=Settlement.Status.HELD,
        release_after__isnull=False,
        release_after__lte=timezone.now(),
    )
    if seller is not None:
        qs = qs.filter(seller=seller)
    released = 0
    for settlement in qs:
        if settlement.order.disputes.filter(status=Dispute.Status.OPEN).exists():
            continue
        settlement.status = Settlement.Status.AVAILABLE
        settlement.save(update_fields=("status", "updated_at"))
        order = settlement.order
        order.status = Order.Status.COMPLETED
        order.completed_at = timezone.now()
        order.save(update_fields=("status", "completed_at", "updated_at"))
        released += 1
    return released


def seller_wallet(seller) -> dict:
    release_due_settlements(seller=seller)
    pending_cents = int(
        Settlement.objects.filter(seller=seller)
        .filter(
            Q(status__in=(Settlement.Status.PENDING, Settlement.Status.HELD))
            | Q(status=Settlement.Status.BLOCKED, order__status=Order.Status.DISPUTED)
        )
        .aggregate(total=Sum("amount_cents"))["total"]
        or 0
    )
    available_cents = int(
        Settlement.objects.filter(
            seller=seller, status=Settlement.Status.AVAILABLE
        ).aggregate(total=Sum("amount_cents"))["total"]
        or 0
    )
    payout_requested_cents = int(
        Settlement.objects.filter(
            seller=seller, status=Settlement.Status.PAYOUT_REQUESTED
        ).aggregate(total=Sum("amount_cents"))["total"]
        or 0
    )
    paid_out_cents = int(
        Settlement.objects.filter(
            seller=seller, status=Settlement.Status.PAID
        ).aggregate(total=Sum("amount_cents"))["total"]
        or 0
    )
    return {
        "pending_cents": pending_cents,
        "available_cents": available_cents,
        "payout_requested_cents": payout_requested_cents,
        "paid_out_cents": paid_out_cents,
        "currency": "BRL",
    }


def _payout_batch_key(*, seller_id, settlements: list[Settlement]) -> str:
    settlement_ids = ":".join(sorted(str(row.id) for row in settlements))
    digest = hashlib.sha256(
        f"{seller_id}:{settlement_ids}".encode("utf-8")
    ).hexdigest()[:40]
    return f"seller-payout:{seller_id}:{digest}"


def _provider_available_amount(balance: dict) -> int:
    raw_available = (
        balance.get("available_amount")
        if balance.get("available_amount") is not None
        else balance.get("available")
    )
    if raw_available is None:
        raw_available = balance.get("amount")
    try:
        return int(raw_available)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "The payment provider balance could not be verified."
        ) from exc


def withdraw_available_balance(*, seller) -> dict:
    release_due_settlements(seller=seller)
    provider = get_commerce_provider()

    with transaction.atomic():
        account = SellerPaymentAccount.objects.select_for_update().get(seller=seller)
        if (
            account.status != SellerPaymentAccount.Status.ACTIVE
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
            amount = sum(row.amount_cents for row in settlements)
        else:
            settlements = list(
                Settlement.objects.select_for_update()
                .filter(seller=seller, status=Settlement.Status.AVAILABLE)
                .order_by("created_at")
            )
            amount = sum(row.amount_cents for row in settlements)
            if amount <= 0:
                raise ValidationError("There is no available balance to withdraw.")

            balance = provider.get_recipient_balance(account.provider_recipient_id)
            available_provider = _provider_available_amount(balance)
            if available_provider < amount:
                raise ValidationError(
                    "The payment provider has not released all proceeds yet."
                )

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
        recipient_id = account.provider_recipient_id

    transfer = provider.create_transfer(
        recipient_id=recipient_id,
        amount_cents=amount,
        idempotency_key=batch_key,
    )
    transfer_id = str(transfer.get("id") or "").strip()
    if not transfer_id:
        raise CommerceProviderError("Pagar.me did not return a transfer id.")

    with transaction.atomic():
        rows = list(
            Settlement.objects.select_for_update().filter(
                seller=seller,
                status=Settlement.Status.PAYOUT_REQUESTED,
                payout_idempotency_key=batch_key,
            )
        )
        for settlement in rows:
            settlement.provider_transfer_id = transfer_id
            settlement.save(update_fields=("provider_transfer_id", "updated_at"))
            LedgerEntry.objects.get_or_create(
                order=settlement.order,
                seller=seller,
                kind=LedgerEntry.Kind.SELLER_PAYOUT,
                provider_reference=transfer_id,
                defaults={
                    "amount_cents": -settlement.amount_cents,
                    "currency": settlement.order.currency,
                    "metadata": {"payout_batch_key": batch_key},
                },
            )
    return {
        "transfer_id": transfer_id,
        "amount_cents": amount,
        "status": transfer.get("status") or "requested",
    }


@transaction.atomic
def finalize_order_refund(
    *, payment: CommercePayment, reason: str = "", provider_status: str = "refunded"
) -> Order:
    payment = (
        CommercePayment.objects.select_for_update()
        .select_related("order", "order__seller")
        .get(pk=payment.pk)
    )
    order = Order.objects.select_for_update().get(pk=payment.order_id)
    settlement = Settlement.objects.select_for_update().get(order=order)
    now = timezone.now()

    payment.status = CommercePayment.Status.REFUNDED
    payment.refunded_at = payment.refunded_at or now
    payment.provider_status = provider_status or payment.provider_status
    payment.save(
        update_fields=("status", "refunded_at", "provider_status", "updated_at")
    )
    order.status = Order.Status.REFUNDED
    order.save(update_fields=("status", "updated_at"))

    if settlement.status != Settlement.Status.PAID:
        settlement.status = Settlement.Status.BLOCKED
        settlement.release_after = None
        settlement.save(update_fields=("status", "release_after", "updated_at"))

    if not order.ledger_entries.filter(
        kind=LedgerEntry.Kind.REFUND,
        provider_reference=payment.provider_charge_id,
    ).exists():
        LedgerEntry.objects.create(
            order=order,
            seller=order.seller,
            kind=LedgerEntry.Kind.REFUND,
            amount_cents=-order.total_cents,
            currency=order.currency,
            provider_reference=payment.provider_charge_id,
            metadata={"reason": reason},
        )
    return order


@transaction.atomic
def refund_order(*, order: Order, reason: str = "") -> Order:
    order = Order.objects.select_for_update().get(pk=order.pk)
    payment = (
        order.payments.select_for_update()
        .filter(status=CommercePayment.Status.APPROVED)
        .order_by("-created_at")
        .first()
    )
    if not payment or not payment.provider_charge_id:
        raise ValidationError("No refundable approved payment was found.")
    settlement = Settlement.objects.select_for_update().get(order=order)
    if settlement.status in {
        Settlement.Status.PAYOUT_REQUESTED,
        Settlement.Status.PAID,
    }:
        raise ValidationError(
            "Seller payout has already started; refund requires manual financial recovery."
        )
    provider = get_commerce_provider()
    provider.cancel_charge(payment.provider_charge_id)
    return finalize_order_refund(
        payment=payment,
        reason=reason,
        provider_status="refunded",
    )
