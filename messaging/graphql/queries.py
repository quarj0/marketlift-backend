from datetime import datetime

import strawberry
from django.db.models import Count, Exists, F, OuterRef, Q
from graphql import GraphQLError

from marketlift.graphql.auth import require_user
from marketlift.realtime.counts import unread_message_count
from messaging.models import Conversation, Message, UserBlock
from messaging.services import get_conversation_for_user

from .mappers import conversation_to_type, message_to_type
from .types import ConversationType, MessageType


def conversation_queryset(user=None):
    qs = Conversation.objects.select_related(
        "buyer",
        "buyer__seller_profile",
        "seller__user",
        "seller__user__seller_profile",
        "listing__seller__user",
        "listing__category",
    ).prefetch_related("listing__media__upload__variants")
    if user is not None and getattr(user, "is_authenticated", False):
        unread_filter = ~Q(messages__sender=user) & (
            (
                Q(buyer=user)
                & (
                    Q(buyer_last_read_at__isnull=True)
                    | Q(messages__created_at__gt=F("buyer_last_read_at"))
                )
            )
            | (
                Q(seller__user=user)
                & (
                    Q(seller_last_read_at__isnull=True)
                    | Q(messages__created_at__gt=F("seller_last_read_at"))
                )
            )
        )
        blocked = UserBlock.objects.filter(blocker=user).filter(
            Q(blocked_id=OuterRef("buyer_id"))
            | Q(blocked_id=OuterRef("seller__user_id"))
        )
        qs = qs.annotate(
            _viewer_unread=Count("messages", filter=unread_filter, distinct=True),
            _viewer_blocked=Exists(blocked),
        )
    return qs


@strawberry.type
class MessagingQuery:
    @strawberry.field
    def my_conversations(
        self, info: strawberry.Info, include_archived: bool = False
    ) -> list[ConversationType]:
        user = require_user(info)
        query = conversation_queryset(user).filter(Q(buyer=user) | Q(seller__user=user))
        if not include_archived:
            query = query.filter(
                Q(buyer=user, buyer_archived_at__isnull=True)
                | Q(seller__user=user, seller_archived_at__isnull=True)
            )
        return [conversation_to_type(item, user) for item in query[:200]]

    @strawberry.field
    def conversation(
        self, info: strawberry.Info, id: strawberry.ID
    ) -> ConversationType:
        user = require_user(info)
        try:
            item = conversation_queryset(user).get(pk=str(id))
            if not item.includes_user(user):
                raise Conversation.DoesNotExist
        except (Conversation.DoesNotExist, ValueError) as exc:
            raise GraphQLError("Conversation not found.") from exc
        return conversation_to_type(item, user)

    @strawberry.field
    def messages(
        self,
        info: strawberry.Info,
        conversation_id: strawberry.ID,
        before: datetime | None = None,
        limit: int = 50,
    ) -> list[MessageType]:
        user = require_user(info)
        conversation = get_conversation_for_user(
            user=user, conversation_id=conversation_id
        )
        limit = min(max(limit, 1), 100)
        query = (
            Message.objects.filter(conversation=conversation)
            .select_related(
                "sender",
                "conversation__buyer",
                "conversation__seller__user",
                "attachment__upload",
            )
            .prefetch_related("attachment__upload__variants")
            .order_by("-created_at")
        )
        if before is not None:
            query = query.filter(created_at__lt=before)
        items = list(query[:limit])
        items.reverse()
        return [message_to_type(item, user) for item in items]

    @strawberry.field
    def unread_message_count(self, info: strawberry.Info) -> int:
        return unread_message_count(require_user(info))
