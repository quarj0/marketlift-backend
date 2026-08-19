from django.contrib import admin

from .models import Conversation, Message, MessageAttachment, UserBlock


class MessageAttachmentInline(admin.StackedInline):
    model = MessageAttachment
    extra = 0
    readonly_fields = ("upload", "name_snapshot", "mime_type_snapshot", "size_snapshot")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "listing_title_snapshot",
        "buyer",
        "seller",
        "last_message_at",
    )
    search_fields = ("listing_title_snapshot", "buyer__email", "seller__user__email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "sender", "created_at")
    search_fields = ("text", "sender__email")
    inlines = [MessageAttachmentInline]
    readonly_fields = ("created_at", "updated_at")


@admin.register(UserBlock)
class UserBlockAdmin(admin.ModelAdmin):
    list_display = ("blocker", "blocked", "created_at")
