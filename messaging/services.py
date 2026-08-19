from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from listings.models import Listing
from notifications.services import create_notification
from uploads.models import UploadAsset
from uploads.services import claim_upload

from .models import Conversation, Message, MessageAttachment, UserBlock

FINAL_UNAVAILABLE_LISTING_STATUSES = {Listing.Status.REJECTED, Listing.Status.REMOVED}


def _require_participant(conversation: Conversation, user):
    if not conversation.includes_user(user):
        raise PermissionDenied("You are not part of this conversation.")
    return conversation


def _blocked_between(user_a, user_b) -> bool:
    return UserBlock.objects.filter(
        Q(blocker=user_a, blocked=user_b) | Q(blocker=user_b, blocked=user_a)
    ).exists()


@transaction.atomic
def start_conversation(*, buyer, listing: Listing):
    if listing.seller.user_id == buyer.pk:
        raise ValidationError("You cannot message yourself about your own listing.")
    if not listing.is_publicly_visible:
        raise ValidationError(
            "This listing is not currently available for new conversations."
        )
    from django.core.exceptions import ObjectDoesNotExist

    try:
        if listing.seller.settings.vacation:
            raise ValidationError("This seller is currently in vacation mode.")
    except ObjectDoesNotExist:
        pass
    if _blocked_between(buyer, listing.seller.user):
        raise ValidationError("Messaging is unavailable between these accounts.")

    conversation, created = Conversation.objects.get_or_create(
        listing=listing,
        buyer=buyer,
        defaults={
            "seller": listing.seller,
            "listing_title_snapshot": listing.title,
        },
    )
    if not created:
        if conversation.seller_id != listing.seller_id:
            conversation.seller = listing.seller
        conversation.listing_title_snapshot = listing.title
        conversation.buyer_archived_at = None
        conversation.save(
            update_fields=(
                "seller",
                "listing_title_snapshot",
                "buyer_archived_at",
                "updated_at",
            )
        )
    return conversation


def get_conversation_for_user(*, user, conversation_id) -> Conversation:
    try:
        conversation = Conversation.objects.select_related(
            "buyer", "seller__user", "listing__category", "listing__seller__user"
        ).get(pk=str(conversation_id))
    except (Conversation.DoesNotExist, ValueError) as exc:
        raise ValidationError("Conversation not found.") from exc
    return _require_participant(conversation, user)


@transaction.atomic
def send_message(
    *,
    user,
    conversation: Conversation,
    text: str = "",
    upload: UploadAsset | None = None,
):
    # Lock only the Conversation row. ``listing`` is nullable, so combining
    # select_for_update() with select_related("listing") makes PostgreSQL try
    # to lock the nullable side of an OUTER JOIN, which PostgreSQL rejects.
    #
    # Keep the row lock for the duration of this transaction, then hydrate the
    # related objects in a separate non-locking query. This preserves message
    # serialization without coupling the service to a backend-specific
    # select_for_update(of=(...)) option.
    locked = Conversation.objects.select_for_update().only("pk").get(pk=conversation.pk)
    conversation = Conversation.objects.select_related(
        "buyer", "seller__user", "listing"
    ).get(pk=locked.pk)
    _require_participant(conversation, user)
    other = conversation.other_user(user)

    if _blocked_between(user, other):
        raise ValidationError("Messaging is blocked between these accounts.")
    if conversation.seller.is_suspended:
        raise ValidationError(
            "Messaging is unavailable while this seller account is suspended."
        )
    if (
        conversation.listing_id
        and conversation.listing.status in FINAL_UNAVAILABLE_LISTING_STATUSES
    ):
        raise ValidationError("Messaging is closed for this listing.")

    text = (text or "").strip()
    if len(text) > 4000:
        raise ValidationError({"text": "Messages cannot exceed 4000 characters."})
    if not text and upload is None:
        raise ValidationError("A message or image is required.")

    claimed_upload = None
    if upload is not None:
        claimed_upload = claim_upload(
            asset=upload, user=user, purpose=UploadAsset.Purpose.MESSAGE_IMAGE
        )

    message = Message.objects.create(conversation=conversation, sender=user, text=text)
    if claimed_upload is not None:
        MessageAttachment.objects.create(
            message=message,
            upload=claimed_upload,
            attachment_type="image",
            name_snapshot=claimed_upload.original_name,
            mime_type_snapshot=claimed_upload.mime_type,
            size_snapshot=claimed_upload.actual_size or claimed_upload.expected_size,
        )

    now = message.created_at
    conversation.last_message_at = now
    conversation.last_message_preview = text[:240] if text else "📷 Photo"
    if conversation.buyer_id == user.pk:
        conversation.buyer_archived_at = None
        conversation.seller_archived_at = None
        update_fields = (
            "last_message_at",
            "last_message_preview",
            "buyer_archived_at",
            "seller_archived_at",
            "updated_at",
        )
    else:
        conversation.seller_archived_at = None
        conversation.buyer_archived_at = None
        update_fields = (
            "last_message_at",
            "last_message_preview",
            "seller_archived_at",
            "buyer_archived_at",
            "updated_at",
        )
    conversation.save(update_fields=update_fields)

    create_notification(
        user=other,
        notification_type="message",
        title=f"New message from {user.full_name or user.email}",
        body=text[:160] if text else "📷 Photo",
        href=f"/messages/{conversation.id}",
        data={"conversationId": str(conversation.id), "messageId": str(message.id)},
    )
    return message


@transaction.atomic
def mark_conversation_read(*, user, conversation: Conversation):
    conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
    role = conversation.role_for(user)
    now = timezone.now()
    if role == "buyer":
        conversation.buyer_last_read_at = now
        conversation.save(update_fields=("buyer_last_read_at", "updated_at"))
    else:
        conversation.seller_last_read_at = now
        conversation.save(update_fields=("seller_last_read_at", "updated_at"))
    return conversation


@transaction.atomic
def set_conversation_archived(*, user, conversation: Conversation, archived: bool):
    conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
    role = conversation.role_for(user)
    value = timezone.now() if archived else None
    field = "buyer_archived_at" if role == "buyer" else "seller_archived_at"
    setattr(conversation, field, value)
    conversation.save(update_fields=(field, "updated_at"))
    return conversation


@transaction.atomic
def block_conversation_user(*, user, conversation: Conversation):
    _require_participant(conversation, user)
    other = conversation.other_user(user)
    UserBlock.objects.get_or_create(blocker=user, blocked=other)
    return conversation


@transaction.atomic
def unblock_conversation_user(*, user, conversation: Conversation):
    _require_participant(conversation, user)
    other = conversation.other_user(user)
    UserBlock.objects.filter(blocker=user, blocked=other).delete()
    return conversation


def is_blocked_by_current_user(*, user, conversation: Conversation) -> bool:
    other = conversation.other_user(user)
    return UserBlock.objects.filter(blocker=user, blocked=other).exists()


def message_is_read(*, message: Message) -> bool:
    conversation = message.conversation
    if message.sender_id == conversation.buyer_id:
        return bool(
            conversation.seller_last_read_at
            and conversation.seller_last_read_at >= message.created_at
        )
    return bool(
        conversation.buyer_last_read_at
        and conversation.buyer_last_read_at >= message.created_at
    )
