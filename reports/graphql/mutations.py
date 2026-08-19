import strawberry
from django.core.exceptions import ValidationError
from graphql import GraphQLError
from marketlift.graphql.auth import request_from_info, require_staff, require_user
from marketlift.graphql.errors import validation_error
from reports.models import Report
from reports.services import (
    create_report,
    dismiss_report,
    move_report_to_review,
    resolve_report,
    save_internal_note,
)
from .inputs import ReportInput
from .mappers import report_to_type
from .types import ReportType


def _report(id):
    try:
        return Report.objects.select_related("reporter").get(pk=str(id))
    except (Report.DoesNotExist, ValueError) as exc:
        raise GraphQLError("Report not found.") from exc


@strawberry.type
class ReportMutation:
    @strawberry.mutation
    def create_report(self, info: strawberry.Info, input: ReportInput) -> ReportType:
        try:
            r = create_report(
                reporter=require_user(info),
                target_type=input.target_type,
                target_id=input.target_id,
                reason=input.reason,
                statement=input.statement,
                priority=input.priority,
            )
        except ValidationError as exc:
            raise validation_error(exc) from exc
        return report_to_type(r)

    @strawberry.mutation
    def move_report_to_review(
        self, info: strawberry.Info, report_id: strawberry.ID, note: str = ""
    ) -> ReportType:
        actor = require_staff(info)
        try:
            r = move_report_to_review(
                report=_report(report_id),
                actor=actor,
                note=note,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(exc) from exc
        return report_to_type(r)

    @strawberry.mutation
    def resolve_report(
        self, info: strawberry.Info, report_id: strawberry.ID, reason: str
    ) -> ReportType:
        actor = require_staff(info)
        try:
            r = resolve_report(
                report=_report(report_id),
                actor=actor,
                reason=reason,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(exc) from exc
        return report_to_type(r)

    @strawberry.mutation
    def dismiss_report(
        self, info: strawberry.Info, report_id: strawberry.ID, reason: str
    ) -> ReportType:
        actor = require_staff(info)
        try:
            r = dismiss_report(
                report=_report(report_id),
                actor=actor,
                reason=reason,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(exc) from exc
        return report_to_type(r)

    @strawberry.mutation
    def save_report_note(
        self, info: strawberry.Info, report_id: strawberry.ID, note: str
    ) -> ReportType:
        actor = require_staff(info)
        try:
            r = save_internal_note(
                report=_report(report_id),
                actor=actor,
                note=note,
                request=request_from_info(info),
            )
        except ValidationError as exc:
            raise validation_error(exc) from exc
        return report_to_type(r)
