import strawberry
from django.core.exceptions import PermissionDenied, ValidationError
from graphql import GraphQLError

from listings.models import Listing
from marketlift.graphql.auth import require_user
from marketlift.graphql.errors import validation_error
from messaging.services import (
    block_conversation_user,
    get_conversation_for_user,
    mark_conversation_read,
    send_message,
    set_conversation_archived,
    start_conversation,
    unblock_conversation_user,
)
from uploads.models import UploadAsset

from .inputs import SendMessageInput
from .mappers import conversation_to_type, message_to_type
from .queries import conversation_queryset
from .types import ConversationType, MessageType


def _conversation(user, conversation_id):
    return get_conversation_for_user(user=user, conversation_id=conversation_id)


@strawberry.type
class MessagingMutation:
    @strawberry.mutation
    def start_conversation(
        self, info: strawberry.Info, listing_id: strawberry.ID
    ) -> ConversationType:
        user = require_user(info)
        try:
            listing = Listing.objects.select_related("seller__user", "category").get(
                pk=str(listing_id)
            )
            item = start_conversation(buyer=user, listing=listing)
            item = conversation_queryset().get(pk=item.pk)
        except (Listing.DoesNotExist, ValueError) as exc:
            raise GraphQLError("Listing not found.") from exc
        except (ValidationError, PermissionDenied) as exc:
            raise validation_error(exc) from exc
        return conversation_to_type(item, user)

    @strawberry.mutation
    def send_message(
        self, info: strawberry.Info, input: SendMessageInput
    ) -> MessageType:
        user = require_user(info)
        conversation = _conversation(user, input.conversation_id)
        upload = None
        if input.upload_id is not None:
            try:
                upload = UploadAsset.objects.get(pk=str(input.upload_id))
            except (UploadAsset.DoesNotExist, ValueError) as exc:
                raise GraphQLError("Upload not found.") from exc
        try:
            message = send_message(
                user=user,
                conversation=conversation,
                text=input.text or "",
                upload=upload,
            )
        except (ValidationError, PermissionDenied) as exc:
            raise validation_error(exc) from exc
        message = Message.objects.select_related(
            "sender",
            "conversation__buyer",
            "conversation__seller__user",
            "attachment__upload",
        ).get(pk=message.pk)
        return message_to_type(message, user)

    @strawberry.mutation
    def mark_conversation_read(
        self, info: strawberry.Info, conversation_id: strawberry.ID
    ) -> bool:
        user = require_user(info)
        try:
            mark_conversation_read(
                user=user, conversation=_conversation(user, conversation_id)
            )
        except (ValidationError, PermissionDenied) as exc:
            raise validation_error(exc) from exc
        return True

    @strawberry.mutation
    def archive_conversation(
        self,
        info: strawberry.Info,
        conversation_id: strawberry.ID,
        archived: bool = True,
    ) -> ConversationType:
        user = require_user(info)
        try:
            item = set_conversation_archived(
                user=user,
                conversation=_conversation(user, conversation_id),
                archived=archived,
            )
            item = conversation_queryset().get(pk=item.pk)
        except (ValidationError, PermissionDenied) as exc:
            raise validation_error(exc) from exc
        return conversation_to_type(item, user)

    @strawberry.mutation
    def block_conversation_user(
        self, info: strawberry.Info, conversation_id: strawberry.ID
    ) -> ConversationType:
        user = require_user(info)
        try:
            item = block_conversation_user(
                user=user, conversation=_conversation(user, conversation_id)
            )
            item = conversation_queryset().get(pk=item.pk)
        except (ValidationError, PermissionDenied) as exc:
            raise validation_error(exc) from exc
        return conversation_to_type(item, user)

    @strawberry.mutation
    def unblock_conversation_user(
        self, info: strawberry.Info, conversation_id: strawberry.ID
    ) -> ConversationType:
        user = require_user(info)
        try:
            item = unblock_conversation_user(
                user=user, conversation=_conversation(user, conversation_id)
            )
            item = conversation_queryset().get(pk=item.pk)
        except (ValidationError, PermissionDenied) as exc:
            raise validation_error(exc) from exc
        return conversation_to_type(item, user)
