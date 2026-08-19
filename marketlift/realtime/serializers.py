from __future__ import annotations

from messaging.models import Message
from notifications.models import Notification


def notification_payload(item: Notification) -> dict:
    return {
        "id": str(item.id),
        "type": item.notification_type,
        "title": item.title,
        "body": item.body,
        "createdAt": item.created_at.isoformat(),
        "read": item.read,
        "href": item.href or None,
        "data": item.data or {},
    }


def message_payload(message: Message) -> dict:
    attachment = None
    try:
        item = message.attachment
    except Exception:
        item = None

    if item is not None:
        attachment = {
            "type": item.attachment_type,
            "url": item.upload.preferred_image_url("detail"),
            "name": item.name_snapshot,
            "mimeType": item.mime_type_snapshot,
            "size": item.size_snapshot,
        }

    sender = message.sender
    return {
        "id": str(message.id),
        "conversationId": str(message.conversation_id),
        "senderId": str(message.sender_id),
        "senderName": sender.full_name or sender.email,
        "text": message.text,
        "createdAt": message.created_at.isoformat(),
        "attachment": attachment,
    }
