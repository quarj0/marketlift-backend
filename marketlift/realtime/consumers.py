from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from channels.auth import get_user
from channels.generic.websocket import JsonWebsocketConsumer
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError

from messaging.services import (
    get_conversation_for_user,
    mark_conversation_read,
    send_message,
)
from notifications.services import mark_all_notifications_read, mark_notification_read
from uploads.models import UploadAsset

from .counts import unread_message_count, unread_notification_count
from .groups import user_group

logger = logging.getLogger(__name__)


class RealtimeConsumer(JsonWebsocketConsumer):
    """One authenticated socket for chat and notification realtime events."""

    def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated or not user.is_active:
            self.close(code=4401)
            return

        self.user = user
        self.private_group = user_group(user.pk)
        if self.channel_layer is None:
            logger.error("Realtime channel layer is not configured.")
            self.close(code=1011)
            return
        try:
            async_to_sync(self.channel_layer.group_add)(
                self.private_group, self.channel_name
            )
        except Exception:
            logger.exception("Unable to join realtime channel group")
            self.close(code=1011)
            return
        self.accept()
        self.send_json(
            {
                "type": "realtime.ready",
                "data": {
                    "userId": str(user.pk),
                    "unreadMessageCount": unread_message_count(user),
                    "unreadNotificationCount": unread_notification_count(user),
                },
            }
        )

    def disconnect(self, close_code):
        group = getattr(self, "private_group", None)
        if group and self.channel_layer is not None:
            try:
                async_to_sync(self.channel_layer.group_discard)(
                    group, self.channel_name
                )
            except Exception:
                logger.warning("Unable to leave realtime channel group", exc_info=True)

    def receive_json(self, content, **kwargs):
        if not isinstance(content, dict):
            self._error("invalid_payload", "WebSocket payload must be a JSON object.")
            return

        # Long-lived sockets can outlive a browser logout/session invalidation.
        # Re-resolve the authenticated user before accepting each client command.
        current_user = async_to_sync(get_user)(self.scope)
        if (
            not current_user
            or not current_user.is_authenticated
            or not current_user.is_active
        ):
            self.close(code=4401)
            return
        self.user = current_user

        action = str(content.get("type") or "").strip()
        request_id = content.get("requestId")

        if self._rate_limited():
            self._error(
                "rate_limited",
                "Too many realtime actions. Try again shortly.",
                action=action or None,
                request_id=request_id,
            )
            return

        try:
            if action == "ping":
                self.send_json({"type": "pong", "data": {}})
                return
            if action == "message.send":
                self._send_message(content, request_id=request_id)
                return
            if action == "conversation.read":
                self._mark_conversation_read(content, request_id=request_id)
                return
            if action == "notification.read":
                self._mark_notification_read(content, request_id=request_id)
                return
            if action == "notification.read_all":
                self._mark_all_notifications_read(request_id=request_id)
                return
            self._error(
                "unsupported_action",
                "Unsupported realtime action.",
                action=action,
                request_id=request_id,
            )
        except (ValidationError, PermissionDenied) as exc:
            self._error(
                "validation_error",
                self._exception_message(exc),
                action=action,
                request_id=request_id,
            )
        except Exception:
            logger.exception("Unhandled realtime action error: %s", action)
            self._error(
                "internal_error",
                "Unable to process realtime action.",
                action=action,
                request_id=request_id,
            )

    def realtime_event(self, event):
        self.send_json({"type": event["event"], "data": event.get("data") or {}})

    def _send_message(self, content, *, request_id=None):
        conversation_id = content.get("conversationId")
        if not conversation_id:
            raise ValidationError("conversationId is required.")

        conversation = get_conversation_for_user(
            user=self.user, conversation_id=conversation_id
        )
        upload = None
        upload_id = content.get("uploadId")
        if upload_id:
            try:
                upload = UploadAsset.objects.get(pk=str(upload_id))
            except (UploadAsset.DoesNotExist, ValueError) as exc:
                raise ValidationError("Upload not found.") from exc

        text = content.get("text") or ""
        if not isinstance(text, str):
            raise ValidationError("text must be a string.")
        message = send_message(
            user=self.user,
            conversation=conversation,
            text=text,
            upload=upload,
        )
        self._ack("message.send", request_id, id=str(message.id))

    def _mark_conversation_read(self, content, *, request_id=None):
        conversation_id = content.get("conversationId")
        if not conversation_id:
            raise ValidationError("conversationId is required.")
        conversation = get_conversation_for_user(
            user=self.user, conversation_id=conversation_id
        )
        mark_conversation_read(user=self.user, conversation=conversation)
        self._ack("conversation.read", request_id, id=str(conversation.id))

    def _mark_notification_read(self, content, *, request_id=None):
        notification_id = content.get("notificationId")
        if not notification_id:
            raise ValidationError("notificationId is required.")
        mark_notification_read(user=self.user, notification_id=notification_id)
        self._ack("notification.read", request_id, id=str(notification_id))

    def _mark_all_notifications_read(self, *, request_id=None):
        count = mark_all_notifications_read(user=self.user)
        self._ack("notification.read_all", request_id, count=count)

    def _ack(self, action, request_id, **data):
        payload = {"action": action, **data}
        if request_id is not None:
            payload["requestId"] = request_id
        self.send_json({"type": "command.ack", "data": payload})

    def _error(self, code, message, *, action=None, request_id=None):
        data = {"code": code, "message": message}
        if action:
            data["action"] = action
        if request_id is not None:
            data["requestId"] = request_id
        self.send_json({"type": "error", "data": data})

    @staticmethod
    def _exception_message(exc):
        if isinstance(exc, ValidationError):
            if getattr(exc, "messages", None):
                return " ".join(str(item) for item in exc.messages)
            if getattr(exc, "message_dict", None):
                return " ".join(
                    str(message)
                    for messages in exc.message_dict.values()
                    for message in messages
                )
        return str(exc)

    def _rate_limited(self) -> bool:
        limit = max(
            1,
            int(
                getattr(
                    settings,
                    "MARKETLIFT_WEBSOCKET_ACTION_RATE_LIMIT_PER_MINUTE",
                    180,
                )
            ),
        )
        key = f"ml:ws:actions:{self.user.pk}"
        try:
            if cache.add(key, 1, timeout=60):
                return False
            try:
                count = cache.incr(key)
            except ValueError:
                cache.set(key, 1, timeout=60)
                count = 1
            return count > limit
        except Exception:
            logger.warning("WebSocket rate-limit cache unavailable", exc_info=True)
            return False
