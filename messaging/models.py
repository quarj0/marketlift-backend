from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from marketlift.common.models import UUIDTimeStampedModel


class Conversation(UUIDTimeStampedModel):
    listing = models.ForeignKey(
        "listings.Listing",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="conversations",
    )
    listing_title_snapshot = models.CharField(max_length=180)
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="buyer_conversations",
    )
    seller = models.ForeignKey(
        "sellers.SellerProfile",
        on_delete=models.PROTECT,
        related_name="conversations",
    )
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_message_preview = models.CharField(max_length=240, blank=True)
    buyer_last_read_at = models.DateTimeField(null=True, blank=True)
    seller_last_read_at = models.DateTimeField(null=True, blank=True)
    buyer_archived_at = models.DateTimeField(null=True, blank=True)
    seller_archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-last_message_at", "-created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("listing", "buyer"),
                condition=Q(listing__isnull=False),
                name="messaging_unique_listing_buyer_conversation",
            )
        ]
        indexes = [
            models.Index(fields=("buyer", "-last_message_at")),
            models.Index(fields=("seller", "-last_message_at")),
        ]

    def includes_user(self, user) -> bool:
        if not user or not getattr(user, "is_authenticated", False):
            return False
        return self.buyer_id == user.pk or self.seller.user_id == user.pk

    def other_user(self, user):
        if self.buyer_id == user.pk:
            return self.seller.user
        if self.seller.user_id == user.pk:
            return self.buyer
        raise ValidationError("This account is not part of the conversation.")

    def role_for(self, user) -> str:
        if self.buyer_id == user.pk:
            return "buyer"
        if self.seller.user_id == user.pk:
            return "seller"
        raise ValidationError("This account is not part of the conversation.")

    def unread_count_for(self, user) -> int:
        role = self.role_for(user)
        last_read = (
            self.buyer_last_read_at if role == "buyer" else self.seller_last_read_at
        )
        query = self.messages.exclude(sender=user)
        if last_read is not None:
            query = query.filter(created_at__gt=last_read)
        return query.count()

    def __str__(self) -> str:
        return f"{self.listing_title_snapshot} · {self.buyer} / {self.seller}"


class Message(UUIDTimeStampedModel):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sent_marketplace_messages",
    )
    text = models.TextField(blank=True)

    class Meta:
        ordering = ("created_at",)
        indexes = [models.Index(fields=("conversation", "created_at"))]

    def __str__(self) -> str:
        return self.text[:80] or "Image message"


class MessageAttachment(UUIDTimeStampedModel):
    message = models.OneToOneField(
        Message, on_delete=models.CASCADE, related_name="attachment"
    )
    upload = models.OneToOneField(
        "uploads.UploadAsset",
        on_delete=models.PROTECT,
        related_name="message_attachment",
    )
    attachment_type = models.CharField(max_length=16, default="image")
    name_snapshot = models.CharField(max_length=255)
    mime_type_snapshot = models.CharField(max_length=120)
    size_snapshot = models.PositiveBigIntegerField()

    def __str__(self) -> str:
        return self.name_snapshot


class UserBlock(UUIDTimeStampedModel):
    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blocked_marketplace_users",
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blocked_by_marketplace_users",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("blocker", "blocked"), name="messaging_unique_user_block"
            ),
            models.CheckConstraint(
                condition=~Q(blocker=F("blocked")), name="messaging_cannot_block_self"
            ),
        ]
        indexes = [models.Index(fields=("blocker", "blocked"))]

    def __str__(self) -> str:
        return f"{self.blocker_id} blocks {self.blocked_id}"
