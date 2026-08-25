import strawberry
from django.db.models import Q, Sum

from marketlift.graphql.auth import require_seller, require_staff
from payments.models import Payment
from .mappers import payment_to_type
from .types import PaymentSummaryType, PaymentType


@strawberry.type
class PaymentQuery:
    @strawberry.field
    def my_payments(
        self, info: strawberry.Info, limit: int = 50, offset: int = 0
    ) -> list[PaymentType]:
        seller = require_seller(info)
        start = max(0, offset)
        end = start + max(1, min(limit, 100))
        qs = Payment.objects.select_related(
            "seller", "seller__user", "seller_plan", "listing", "promotion_product"
        ).filter(seller=seller)[start:end]
        return [payment_to_type(p) for p in qs]

    @strawberry.field
    def payment(self, info: strawberry.Info, id: strawberry.ID) -> PaymentType | None:
        seller = require_seller(info)
        try:
            p = Payment.objects.select_related(
                "seller", "seller_plan", "listing", "promotion_product"
            ).get(pk=str(id), seller=seller)
        except (Payment.DoesNotExist, ValueError):
            return None
        return payment_to_type(p)

    @strawberry.field
    def admin_payment(
        self, info: strawberry.Info, id: strawberry.ID
    ) -> PaymentType | None:
        require_staff(info, roles={"admin", "finance"})
        try:
            payment = Payment.objects.select_related(
                "seller", "seller__user", "seller_plan", "listing", "promotion_product"
            ).get(pk=str(id))
        except (Payment.DoesNotExist, ValueError):
            return None
        return payment_to_type(payment)

    @strawberry.field
    def admin_payments(
        self,
        info: strawberry.Info,
        search: str | None = None,
        status: str | None = None,
        purpose: str | None = None,
        method: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PaymentType]:
        require_staff(info, roles={"admin", "finance"})
        qs = Payment.objects.select_related(
            "seller", "seller__user", "seller_plan", "listing", "promotion_product"
        ).all()
        if search:
            qs = qs.filter(
                Q(reference__icontains=search)
                | Q(provider_order_id__icontains=search)
                | Q(seller__display_name__icontains=search)
                | Q(seller__user__email__icontains=search)
            )
        if status:
            qs = qs.filter(status=status)
        if purpose:
            qs = qs.filter(purpose=purpose)
        if method:
            qs = qs.filter(method=method)
        start = max(0, offset)
        end = start + max(1, min(limit, 100))
        return [payment_to_type(p) for p in qs[start:end]]

    @strawberry.field
    def payment_summary(self, info: strawberry.Info) -> PaymentSummaryType:
        require_staff(info, roles={"admin", "finance"})
        qs = Payment.objects.all()
        paid = qs.filter(status=Payment.Status.PAID)
        refunded = qs.filter(status=Payment.Status.REFUNDED)
        paid_count = paid.count()
        failed_count = qs.filter(status=Payment.Status.FAILED).count()
        completed = paid_count + failed_count
        return PaymentSummaryType(
            paid_total=float(paid.aggregate(v=Sum("amount"))["v"] or 0),
            refunded_total=float(refunded.aggregate(v=Sum("amount"))["v"] or 0),
            paid_count=paid_count,
            failed_count=failed_count,
            pending_count=qs.filter(status=Payment.Status.PENDING).count(),
            success_rate=round((paid_count / completed * 100), 2) if completed else 0.0,
        )
