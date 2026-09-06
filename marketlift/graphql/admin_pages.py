"""Bounded admin pages with matching server-side search, status and totals."""

from dataclasses import field
from uuid import UUID
import strawberry
from django.db.models import Q
from accounts.models import User
from accounts.graphql.types import AdminUserType
from accounts.graphql.mappers import admin_user_to_type
from sellers.graphql.types import AdminSellerType
from sellers.graphql.queries import seller_queryset
from sellers.graphql.mappers import admin_seller_to_type
from listings.models import Listing
from listings.graphql.types import ListingType
from listings.graphql.mappers import listing_queryset, listing_to_type
from reports.models import Report
from reports.graphql.types import ReportType
from reports.graphql.mappers import report_to_type
from moderation.models import ModerationCase
from moderation.graphql.types import ModerationCaseType
from moderation.graphql.mappers import moderation_case_to_type
from support.graphql.types import SupportTicketType
from support.graphql.queries import ticket_queryset
from support.graphql.mappers import ticket_to_type
from audit.models import AuditEvent
from audit.graphql.types import AuditEventType
from audit.graphql.queries import _map as audit_to_type
from .auth import require_staff
from .errors import validation_error
from django.core.exceptions import ValidationError


@strawberry.type
class AdminRecordPage:
    total_count: int
    admin_users: list[AdminUserType] = field(default_factory=list)
    admin_sellers: list[AdminSellerType] = field(default_factory=list)
    admin_listings: list[ListingType] = field(default_factory=list)
    reports: list[ReportType] = field(default_factory=list)
    moderation_queue: list[ModerationCaseType] = field(default_factory=list)
    support_tickets: list[SupportTicketType] = field(default_factory=list)
    audit_events: list[AuditEventType] = field(default_factory=list)


def records(area, info):
    roles = (
        {"admin", "support"}
        if area == "support"
        else (
            {"admin", "moderator"}
            if area in {"moderation", "reports", "activity"}
            else {"admin", "moderator", "support"}
        )
    )
    require_staff(info, roles=roles)
    if area == "users":
        return (
            User.objects.select_related("seller_profile"),
            ["full_name", "email", "phone", "city"],
            "date_joined",
            "admin_users",
            admin_user_to_type,
        )
    if area == "sellers":
        return (
            seller_queryset(admin=True),
            ["display_name", "user__full_name", "user__email", "user__city"],
            "created_at",
            "admin_sellers",
            admin_seller_to_type,
        )
    if area in {"listings", "moderation"}:
        qs = Listing.objects.all()
        if area == "moderation":
            qs = qs.filter(moderation_case__isnull=False)
        return (
            qs,
            [
                "title",
                "seller__display_name",
                "seller__user__email",
                "category_name_snapshot",
                "category__name",
            ],
            "created_at",
            "admin_listings",
            listing_to_type,
        )
    if area == "reports":
        return (
            Report.objects.select_related(
                "reporter",
                "listing",
                "seller__user",
                "user_target",
                "message",
                "assigned_to",
            ),
            [
                "reference",
                "reason",
                "statement",
                "reporter__full_name",
                "listing__title",
            ],
            "created_at",
            "reports",
            report_to_type,
        )
    if area == "support":
        return (
            ticket_queryset(internal=True),
            [
                "reference",
                "subject",
                "user__full_name",
                "user__email",
                "category",
                "priority",
            ],
            "updated_at",
            "support_tickets",
            lambda row: ticket_to_type(row, include_internal=True),
        )
    if area == "activity":
        return (
            AuditEvent.objects.all(),
            ["actor_name", "actor_email", "action", "target_label", "target_id"],
            "created_at",
            "audit_events",
            audit_to_type,
        )
    raise validation_error(ValidationError("Unsupported admin area."))


def filter_status(qs, area, status):
    value = (status or "").lower()
    if value in {"", "all"}:
        return qs
    if area == "users":
        filters = {
            "active": Q(is_active=True, suspended_at__isnull=True),
            "pending": Q(is_active=False, suspended_at__isnull=True),
            "suspended": Q(suspended_at__isnull=False),
        }
    elif area == "sellers":
        filters = {
            "active": Q(is_suspended=False, verified_at__isnull=True),
            "verified": Q(is_suspended=False, verified_at__isnull=False),
            "pending": Q(verified_at__isnull=True, is_suspended=False),
            "suspended": Q(is_suspended=True),
        }
    elif area in {"listings", "moderation"}:
        if value == "deleted":
            return qs.filter(seller_deleted_at__isnull=False)
        return qs.filter(
            seller_deleted_at__isnull=True,
            status={
                "active": "published",
                "pending": "draft",
                "review": "under_review",
            }.get(value, value),
        )
    elif area in {"reports", "support"}:
        return qs.filter(status=value)
    else:
        return qs
    return qs.filter(filters[value]) if value in filters else qs.none()


@strawberry.type
class AdminPaginationQuery:
    @strawberry.field
    def admin_record_page(
        self,
        info: strawberry.Info,
        area: str,
        q: str = "",
        status: str = "",
        limit: int = 25,
        offset: int = 0,
        record_id: str | None = None,
    ) -> AdminRecordPage:
        qs, fields, ordering, name, mapper = records(area, info)
        if len(q) > 160 or offset < 0 or limit < 1 or limit > 100:
            raise validation_error(ValidationError("Invalid admin page parameters."))
        if record_id:
            try:
                qs = qs.filter(pk=UUID(record_id))
            except ValueError as exc:
                raise validation_error(ValidationError("Invalid record ID.")) from exc
        if q.strip():
            matching = Q()
            for column in fields:
                matching |= Q(**{f"{column}__icontains": q.strip()})
            try:
                matching |= Q(pk=UUID(q.strip()))
                if area == "reports":
                    matching |= Q(listing_id=UUID(q.strip()))
            except ValueError:
                pass
            qs = qs.filter(matching)
        qs = filter_status(qs, area, status)
        total = qs.count()
        ids = list(
            qs.order_by(f"-{ordering}", "-id").values_list("pk", flat=True)[
                offset : offset + limit
            ]
        )
        if area in {"listings", "moderation"}:
            qs = listing_queryset(qs)
        by_id = {row.pk: row for row in qs.filter(pk__in=ids)}
        if area == "sellers":
            from subscriptions.models import SellerSubscription, SellerPlan
            from django.utils import timezone

            plans = dict(
                SellerSubscription.objects.filter(
                    seller_id__in=ids,
                    status="active",
                    current_period_end__gt=timezone.now(),
                ).values_list("seller_id", "plan__name")
            )
            free_name = (
                SellerPlan.objects.filter(code="free", active=True)
                .values_list("name", flat=True)
                .first()
                or "Free"
            )
            for row in by_id.values():
                row._admin_plan_name = plans.get(row.pk, free_name)
        if area in {"listings", "moderation"}:
            from django.db.models import Count

            counts = dict(
                Report.objects.filter(listing_id__in=ids)
                .values("listing_id")
                .annotate(n=Count("pk"))
                .values_list("listing_id", "n")
            )
            for row in by_id.values():
                row._admin_report_count = counts.get(row.pk, 0)
        page = AdminRecordPage(
            total_count=total, **{name: [mapper(by_id[pk]) for pk in ids]}
        )
        if area == "moderation":
            page.moderation_queue = [
                moderation_case_to_type(row)
                for row in ModerationCase.objects.select_related(
                    "listing", "decided_by"
                ).filter(listing_id__in=ids)
            ]
        if area == "reports":
            related = [row.listing_id for row in by_id.values() if row.listing_id]
            page.admin_listings = [
                listing_to_type(row)
                for row in listing_queryset(Listing.objects.filter(pk__in=related))
            ]
        if area == "listings" and record_id:
            staff = require_staff(info)
            if staff.is_superuser or staff.admin_role in {
                "super_admin",
                "admin",
                "moderator",
            }:
                related_reports = (
                    Report.objects.select_related(
                        "reporter",
                        "listing",
                        "seller__user",
                        "user_target",
                        "message",
                        "assigned_to",
                    )
                    .filter(listing_id__in=ids)
                    .order_by("-created_at", "-id")[:100]
                )
                page.reports = [report_to_type(row) for row in related_reports]
                page.moderation_queue = [
                    moderation_case_to_type(row)
                    for row in ModerationCase.objects.select_related(
                        "listing", "decided_by"
                    ).filter(listing_id__in=ids)
                ]
        return page
