import strawberry
from marketlift.graphql.auth import require_staff, require_user
from reports.models import Report
from .mappers import report_to_type
from .types import ReportType


@strawberry.type
class ReportQuery:
    @strawberry.field
    def my_reports(self, info: strawberry.Info, limit: int = 50) -> list[ReportType]:
        return [
            report_to_type(r)
            for r in Report.objects.select_related(
                "reporter",
                "listing",
                "seller__user",
                "user_target",
                "message",
                "assigned_to",
            ).filter(reporter=require_user(info))[: max(1, min(limit, 100))]
        ]

    @strawberry.field
    def reports(
        self,
        info: strawberry.Info,
        status: str | None = None,
        priority: str | None = None,
        target_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ReportType]:
        require_staff(info, roles={"admin", "moderator"})
        qs = Report.objects.select_related(
            "reporter",
            "listing",
            "seller__user",
            "user_target",
            "message",
            "assigned_to",
        )
        if status:
            qs = qs.filter(status=status)
        if priority:
            qs = qs.filter(priority=priority)
        if target_type:
            qs = qs.filter(target_type=target_type)
        start = max(0, offset)
        end = start + max(1, min(limit, 100))
        return [report_to_type(r) for r in qs[start:end]]

    @strawberry.field
    def report(self, info: strawberry.Info, id: str) -> ReportType | None:
        require_staff(info, roles={"admin", "moderator"})
        try:
            r = (
                Report.objects.select_related(
                    "reporter",
                    "listing",
                    "seller__user",
                    "user_target",
                    "message",
                    "assigned_to",
                ).get(pk=id)
                if len(id) > 20
                else Report.objects.select_related(
                    "reporter",
                    "listing",
                    "seller__user",
                    "user_target",
                    "message",
                    "assigned_to",
                ).get(reference=id)
            )
        except (Report.DoesNotExist, ValueError):
            return None
        return report_to_type(r)
