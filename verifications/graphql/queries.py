import strawberry
from django.db.models import Q
from django.utils import timezone

from marketlift.graphql.auth import require_seller, require_staff
from verifications.models import VerificationSubmission
from .mappers import verification_to_type
from .types import VerificationQueueSummaryType, VerificationType


@strawberry.type
class VerificationQuery:
    @strawberry.field
    def my_seller_verification(self, info: strawberry.Info) -> VerificationType | None:
        seller = require_seller(info)
        item = (
            VerificationSubmission.objects.filter(seller=seller)
            .order_by("-submitted_at")
            .first()
        )
        return verification_to_type(item) if item else None

    @strawberry.field
    def verifications(
        self,
        info: strawberry.Info,
        search: str | None = None,
        status: str | None = None,
        risk_level: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[VerificationType]:
        require_staff(info, roles={"admin", "moderator"})
        qs = VerificationSubmission.objects.select_related(
            "seller", "seller__user"
        ).all()
        if search:
            qs = qs.filter(
                Q(seller__display_name__icontains=search)
                | Q(seller__user__full_name__icontains=search)
                | Q(seller__user__email__icontains=search)
                | Q(cpf_masked__icontains=search)
            )
        if status:
            qs = qs.filter(status=status)
        if risk_level:
            qs = qs.filter(risk_level=risk_level)
        start = max(0, offset)
        end = start + max(1, min(limit, 100))
        return [verification_to_type(v) for v in qs[start:end]]

    @strawberry.field
    def verification(
        self, info: strawberry.Info, id: strawberry.ID
    ) -> VerificationType | None:
        require_staff(info, roles={"admin", "moderator"})
        try:
            item = VerificationSubmission.objects.select_related(
                "seller", "seller__user"
            ).get(pk=str(id))
        except (VerificationSubmission.DoesNotExist, ValueError):
            return None
        return verification_to_type(item)

    @strawberry.field
    def verification_queue_summary(
        self, info: strawberry.Info
    ) -> VerificationQueueSummaryType:
        require_staff(info, roles={"admin", "moderator"})
        today = timezone.localdate()
        return VerificationQueueSummaryType(
            pending=VerificationSubmission.objects.filter(
                status=VerificationSubmission.Status.PENDING
            ).count(),
            review=VerificationSubmission.objects.filter(
                status=VerificationSubmission.Status.REVIEW
            ).count(),
            verified_today=VerificationSubmission.objects.filter(
                status=VerificationSubmission.Status.VERIFIED, decided_at__date=today
            ).count(),
            rejected_today=VerificationSubmission.objects.filter(
                status=VerificationSubmission.Status.REJECTED, decided_at__date=today
            ).count(),
        )
