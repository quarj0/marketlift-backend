from decimal import Decimal

from messaging.models import Message
from messaging.services import is_blocked_by_current_user, message_is_read

from .types import (
    ConversationListingType,
    ConversationType,
    ConversationUserType,
    MessageAttachmentType,
    MessageType,
)


def _seller_profile(user):
    try:
        return user.seller_profile
    except Exception:
        return None


def _seller_verified(user) -> bool:
    profile = _seller_profile(user)
    return bool(profile and profile.verified)


def conversation_to_type(conversation, user) -> ConversationType:
    other = conversation.other_user(user)
    role = conversation.role_for(user)
    listing = conversation.listing
    primary_image = None
    if listing is not None:
        media = list(listing.media.all())
        if media:
            primary_image = media[0].url
    last_message = conversation.last_message_preview
    archived = (
        conversation.buyer_archived_at is not None
        if role == "buyer"
        else conversation.seller_archived_at is not None
    )
    return ConversationType(
        id=str(conversation.id),
        participant=ConversationUserType(
            id=str(other.id),
            name=other.full_name or other.email,
            avatar_url=other.avatar_url or None,
            verified_seller=_seller_verified(other),
            is_seller=_seller_profile(other) is not None,
        ),
        listing=ConversationListingType(
            id=str(listing.id) if listing else None,
            slug=listing.slug if listing else None,
            title=listing.title if listing else conversation.listing_title_snapshot,
            price=(
                float(listing.price) if listing and listing.price is not None else None
            ),
            primary_image=primary_image,
            status=listing.status if listing else None,
        ),
        last_message=last_message,
        last_message_at=conversation.last_message_at,
        unread=conversation.unread_count_for(user),
        archived=archived,
        blocked=is_blocked_by_current_user(user=user, conversation=conversation),
    )


def message_to_type(message: Message, user) -> MessageType:
    attachment = None
    if hasattr(message, "attachment"):
        item = message.attachment
        attachment = MessageAttachmentType(
            type=item.attachment_type,
            url=item.upload.content_url,
            name=item.name_snapshot,
            mime_type=item.mime_type_snapshot,
            size=item.size_snapshot,
        )
    return MessageType(
        id=str(message.id),
        conversation_id=str(message.conversation_id),
        sender_id=str(message.sender_id),
        sender="me" if message.sender_id == user.pk else "participant",
        text=message.text,
        created_at=message.created_at,
        read=message_is_read(message=message),
        attachment=attachment,
    )
