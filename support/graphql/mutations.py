import strawberry
from django.core.exceptions import PermissionDenied, ValidationError
from graphql import GraphQLError
from marketlift.graphql.auth import require_staff, require_user
from marketlift.graphql.errors import validation_error
from support.models import SupportTicket
from support.services import add_customer_message, create_ticket, staff_reply
from uploads.models import UploadAsset
from .inputs import CreateSupportTicketInput
from .mappers import message_to_type, ticket_to_type
from .types import SupportMessageType, SupportTicketType


@strawberry.type
class SupportMutation:
    @strawberry.mutation
    def create_support_ticket(
        self, info: strawberry.Info, input: CreateSupportTicketInput
    ) -> SupportTicketType:
        u = require_user(info)
        try:
            upload = (
                UploadAsset.objects.get(pk=str(input.upload_id))
                if input.upload_id
                else None
            )
            return ticket_to_type(
                create_ticket(
                    user=u,
                    subject=input.subject,
                    category=input.category,
                    message=input.message,
                    upload=upload,
                    request=getattr(info.context, "request", info.context),
                )
            )
        except UploadAsset.DoesNotExist:
            raise GraphQLError("Upload not found.")
        except ValidationError as e:
            raise validation_error(e)

    @strawberry.mutation
    def reply_support_ticket(
        self,
        info: strawberry.Info,
        ticket_id: strawberry.ID,
        message: str,
        upload_id: strawberry.ID | None = None,
    ) -> SupportMessageType:
        u = require_user(info)
        try:
            t = SupportTicket.objects.get(pk=str(ticket_id))
            upload = UploadAsset.objects.get(pk=str(upload_id)) if upload_id else None
            return message_to_type(
                add_customer_message(user=u, ticket=t, message=message, upload=upload)
            )
        except (SupportTicket.DoesNotExist, UploadAsset.DoesNotExist):
            raise GraphQLError("Ticket or upload not found.")
        except (ValidationError, PermissionDenied) as e:
            raise (
                validation_error(e)
                if isinstance(e, ValidationError)
                else GraphQLError(str(e))
            )

    @strawberry.mutation
    def admin_reply_support_ticket(
        self,
        info: strawberry.Info,
        ticket_id: strawberry.ID,
        message: str,
        internal: bool = False,
        status: str | None = None,
    ) -> SupportTicketType:
        staff = require_staff(info)
        try:
            t = SupportTicket.objects.get(pk=str(ticket_id))
            staff_reply(
                staff=staff,
                ticket=t,
                message=message,
                internal=internal,
                status=status,
                request=getattr(info.context, "request", info.context),
            )
            t.refresh_from_db()
            return ticket_to_type(t, True)
        except SupportTicket.DoesNotExist:
            raise GraphQLError("Ticket not found.")
        except (ValidationError, PermissionDenied) as e:
            raise (
                validation_error(e)
                if isinstance(e, ValidationError)
                else GraphQLError(str(e))
            )
