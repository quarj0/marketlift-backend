from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model

from messaging.models import Conversation, Message
from notifications.models import Notification

from .counts import unread_message_count, unread_notification_count
from .groups import user_group
from .serializers import message_payload, notification_payload

logger = logging.getLogger(__name__)
User = get_user_model()


def _send(user_id, event_name: str, data: dict) -> None:
    """Best-effort delivery. Database state remains the source of truth."""
    try:
        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(layer.group_send)(
            user_group(user_id),
            {
                "type": "realtime.event",
                "event": event_name,
                "data": data,
            },
        )
    except Exception:
        logger.warning(
            "Realtime event delivery failed: event=%s user=%s",
            event_name,
            user_id,
            exc_info=True,
        )


def publish_notification_created(notification_id) -> None:
    try:
        item = Notification.objects.select_related("user").get(pk=notification_id)
    except Notification.DoesNotExist:
        return
    _send(
        item.user_id,
        "notification.created",
        {
            "notification": notification_payload(item),
            "unreadNotificationCount": unread_notification_count(item.user),
        },
    )


def publish_notification_read(notification_id, user_id) -> None:
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return
    _send(
        user_id,
        "notification.read",
        {
            "notificationId": str(notification_id),
            "unreadNotificationCount": unread_notification_count(user),
        },
    )


def publish_notifications_read_all(user_id) -> None:
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return
    _send(
        user_id,
        "notification.read_all",
        {"unreadNotificationCount": unread_notification_count(user)},
    )


def _message_for_realtime(message_id):
    return (
        Message.objects.select_related(
            "sender",
            "conversation__buyer",
            "conversation__seller__user",
            "attachment__upload",
        )
        .prefetch_related("attachment__upload__variants")
        .get(pk=message_id)
    )


def publish_message_created(message_id) -> None:
    try:
        message = _message_for_realtime(message_id)
    except Message.DoesNotExist:
        return

    conversation = message.conversation
    users = (conversation.buyer, conversation.seller.user)
    payload = message_payload(message)
    for viewer in users:
        _send(
            viewer.pk,
            "message.created",
            {
                "message": payload,
                "conversationUnreadCount": conversation.unread_count_for(viewer),
                "unreadMessageCount": unread_message_count(viewer),
            },
        )


def publish_conversation_read(conversation_id, reader_id) -> None:
    try:
        conversation = Conversation.objects.select_related("buyer", "seller__user").get(
            pk=conversation_id
        )
        reader = (
            conversation.buyer
            if conversation.buyer_id == reader_id
            else conversation.seller.user
        )
    except Conversation.DoesNotExist:
        return

    if reader.pk != reader_id:
        return

    read_at = (
        conversation.buyer_last_read_at
        if conversation.buyer_id == reader_id
        else conversation.seller_last_read_at
    )
    for viewer in (conversation.buyer, conversation.seller.user):
        _send(
            viewer.pk,
            "conversation.read",
            {
                "conversationId": str(conversation.id),
                "readerId": str(reader_id),
                "readAt": read_at.isoformat() if read_at else None,
                "unreadMessageCount": unread_message_count(viewer),
            },
        )
