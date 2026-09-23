from __future__ import annotations

from messaging.graphql.mappers import conversation_to_type, message_to_type


def serialize_conversation(conversation, user) -> dict:
    item = conversation_to_type(conversation, user)
    return {
        "id": str(item.id),
        "participant": {
            "id": str(item.participant.id),
            "name": item.participant.name,
            "avatarUrl": item.participant.avatar_url,
            "verifiedSeller": item.participant.verified_seller,
            "isSeller": item.participant.is_seller,
            "phone": item.participant.phone,
            "online": item.participant.online,
        },
        "listing": {
            "id": str(item.listing.id) if item.listing.id is not None else None,
            "slug": item.listing.slug,
            "title": item.listing.title,
            "price": item.listing.price,
            "primaryImage": item.listing.primary_image,
            "status": item.listing.status,
            "deleted": item.listing.deleted,
            "countryCode": item.listing.country_code,
            "state": item.listing.state,
            "stateCode": item.listing.state_code,
            "city": item.listing.city,
            "district": item.listing.district,
        },
        "lastMessage": item.last_message,
        "lastMessageAt": item.last_message_at.isoformat() if item.last_message_at else None,
        "unread": item.unread,
        "archived": item.archived,
        "blocked": item.blocked,
    }


def serialize_message(message, user) -> dict:
    item = message_to_type(message, user)
    attachment = None
    if item.attachment is not None:
        attachment = {
            "type": item.attachment.type,
            "url": item.attachment.url,
            "name": item.attachment.name,
            "mimeType": item.attachment.mime_type,
            "size": item.attachment.size,
        }
    return {
        "id": str(item.id),
        "conversationId": str(item.conversation_id),
        "senderId": str(item.sender_id),
        "sender": item.sender,
        "text": item.text,
        "createdAt": item.created_at.isoformat(),
        "read": item.read,
        "attachment": attachment,
    }
