import strawberry
from django.db.models import Q

from categories.models import Category
from listings.models import Listing
from marketlift.graphql.auth import require_seller, require_staff, require_user
from marketlift.graphql.errors import not_found_error

from commerce.models import Dispute, Order, SellerPaymentAccount
from commerce.policy_models import CategoryCommercePolicy
from commerce.services import listing_commerce_state, resolve_category_policy, seller_wallet

from .mappers import (
    category_policy_to_type,
    dispute_to_type,
    listing_commerce_to_type,
    order_to_type,
    payment_account_to_type,
    wallet_to_type,
)
from .types import (
    CategoryCommercePolicyType,
    DisputeType,
    ListingCommerceType,
    OrderType,
    SellerPaymentAccountType,
    SellerWalletType,
)


SELLER_ADDRESS_VISIBLE_STATES = {
    Order.Status.AWAITING_SELLER,
    Order.Status.PROCESSING,
    Order.Status.SHIPPED,
    Order.Status.OUT_FOR_DELIVERY,
    Order.Status.DELIVERED,
    Order.Status.COMPLETED,
    Order.Status.DISPUTED,
}


def _listing(value: str) -> Listing:
    query = Listing.objects.select_related(
        "seller", "seller__user", "category", "category__parent"
    )
    try:
        return query.get(Q(pk=value) | Q(slug=value))
    except (Listing.DoesNotExist, ValueError) as exc:
        raise not_found_error("Listing", code="LISTING_NOT_FOUND") from exc


def _order_queryset():
    return Order.objects.select_related(
        "buyer", "seller", "seller__user", "listing"
    ).prefetch_related("payments", "disputes")


def _slice(qs, *, offset: int, limit: int, max_limit: int):
    safe_offset = max(0, offset)
    safe_limit = max(1, min(limit, max_limit))
    return qs[safe_offset : safe_offset + safe_limit]


@strawberry.type
class CommerceQuery:
    @strawberry.field
    def listing_commerce(
        self, info: strawberry.Info, listing_id: str
    ) -> ListingCommerceType:
        return listing_commerce_to_type(listing_commerce_state(_listing(listing_id)))

    @strawberry.field
    def category_commerce_policy(
        self, info: strawberry.Info, category_id: str
    ) -> CategoryCommercePolicyType:
        try:
            category = Category.objects.select_related("parent").get(slug=category_id)
        except Category.DoesNotExist as exc:
            raise not_found_error("Category", code="CATEGORY_NOT_FOUND") from exc
        resolved = resolve_category_policy(category)
        policy = CategoryCommercePolicy(
            category=category,
            mode=resolved.mode,
            requires_verified_seller=resolved.requires_verified_seller,
            max_checkout_value_cents=resolved.max_checkout_value_cents,
            shipping_allowed=resolved.shipping_allowed,
            local_delivery_allowed=resolved.local_delivery_allowed,
            pickup_allowed=resolved.pickup_allowed,
        )
        return category_policy_to_type(category, policy)

    @strawberry.field
    def my_orders(
        self,
        info: strawberry.Info,
        limit: int = 50,
        offset: int = 0,
    ) -> list[OrderType]:
        user = require_user(info)
        orders = _slice(
            _order_queryset().filter(buyer=user),
            offset=offset,
            limit=limit,
            max_limit=100,
        )
        return [order_to_type(order, buyer_view=True) for order in orders]

    @strawberry.field
    def my_order(self, info: strawberry.Info, order_id: strawberry.ID) -> OrderType:
        user = require_user(info)
        try:
            order = _order_queryset().get(pk=str(order_id), buyer=user)
        except (Order.DoesNotExist, ValueError) as exc:
            raise not_found_error("Order", code="ORDER_NOT_FOUND") from exc
        return order_to_type(order, buyer_view=True)

    @strawberry.field
    def my_seller_orders(
        self,
        info: strawberry.Info,
        limit: int = 100,
        offset: int = 0,
    ) -> list[OrderType]:
        seller = require_seller(info)
        orders = _slice(
            _order_queryset().filter(seller=seller),
            offset=offset,
            limit=limit,
            max_limit=200,
        )
        return [
            order_to_type(
                order,
                buyer_view=False,
                include_shipping_address=(
                    order.paid_at is not None
                    and order.status in SELLER_ADDRESS_VISIBLE_STATES
                ),
            )
            for order in orders
        ]

    @strawberry.field
    def my_seller_wallet(self, info: strawberry.Info) -> SellerWalletType:
        seller = require_seller(info)
        return wallet_to_type(seller_wallet(seller))

    @strawberry.field
    def my_seller_payment_account(
        self, info: strawberry.Info
    ) -> SellerPaymentAccountType | None:
        seller = require_seller(info)
        try:
            account = seller.payment_account
        except SellerPaymentAccount.DoesNotExist:
            return None
        return payment_account_to_type(account)

    @strawberry.field
    def admin_commerce_orders(
        self,
        info: strawberry.Info,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[OrderType]:
        require_staff(info)
        qs = _order_queryset()
        if status:
            qs = qs.filter(status=status)
        orders = _slice(qs, offset=offset, limit=limit, max_limit=250)
        return [order_to_type(order, buyer_view=False) for order in orders]

    @strawberry.field
    def admin_commerce_disputes(
        self,
        info: strawberry.Info,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DisputeType]:
        require_staff(info)
        qs = Dispute.objects.select_related("order").order_by("-created_at")
        if status:
            qs = qs.filter(status=status)
        rows = _slice(qs, offset=offset, limit=limit, max_limit=250)
        return [dispute_to_type(row) for row in rows]
