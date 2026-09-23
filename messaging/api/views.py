from __future__ import annotations

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from listings.models import Listing
from marketlift.realtime.counts import unread_message_count, unread_notification_count
from messaging.graphql.queries import conversation_queryset
from messaging.models import Conversation, Message
from messaging.services import (
    get_conversation_for_user,
    mark_conversation_read,
    send_message,
    start_conversation,
)
from uploads.models import UploadAsset

from .serializers import serialize_conversation, serialize_message


def _raise_service_error(exc):
    if isinstance(exc, DjangoPermissionDenied):
        raise PermissionDenied(str(exc)) from exc
    if isinstance(exc, DjangoValidationError):
        if getattr(exc, "message_dict", None):
            raise ValidationError(exc.message_dict) from exc
        raise ValidationError(getattr(exc, "messages", [str(exc)])) from exc
    raise exc


def _conversation_for_user(user, conversation_id):
    try:
        return get_conversation_for_user(
            user=user,
            conversation_id=conversation_id,
        )
    except DjangoValidationError as exc:
        raise NotFound("Conversation not found.") from exc


class ConversationCollectionView(APIView):
    def get(self, request):
        try:
            limit = max(1, min(int(request.query_params.get("limit", 50)), 100))
            offset = max(0, int(request.query_params.get("offset", 0)))
        except (TypeError, ValueError) as exc:
            raise ValidationError({"pagination": "limit and offset must be integers."}) from exc

        query = conversation_queryset(request.user).filter(
            Q(buyer=request.user) | Q(seller__user=request.user)
        )
        if request.query_params.get("includeArchived") != "true":
            query = query.filter(
                Q(buyer=request.user, buyer_archived_at__isnull=True)
                | Q(seller__user=request.user, seller_archived_at__isnull=True)
            )
        query = query.order_by("-last_message_at", "-created_at", "-id")
        items = [
            serialize_conversation(item, request.user)
            for item in query[offset : offset + limit]
        ]
        return Response({"results": items})

    def post(self, request):
        listing_id = str(request.data.get("listingId") or "").strip()
        if not listing_id:
            raise ValidationError({"listingId": "listingId is required."})
        try:
            listing = Listing.objects.select_related("seller__user", "category").get(
                pk=listing_id
            )
            conversation = start_conversation(buyer=request.user, listing=listing)
            conversation = conversation_queryset(request.user).get(pk=conversation.pk)
        except (Listing.DoesNotExist, ValueError) as exc:
            raise NotFound("Listing not found.") from exc
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            _raise_service_error(exc)
        return Response(serialize_conversation(conversation, request.user), status=201)


class ConversationDetailView(APIView):
    def get(self, request, conversation_id):
        try:
            item = conversation_queryset(request.user).get(pk=str(conversation_id))
            if not item.includes_user(request.user):
                raise Conversation.DoesNotExist
        except (Conversation.DoesNotExist, ValueError) as exc:
            raise NotFound("Conversation not found.") from exc
        return Response(serialize_conversation(item, request.user))


class ConversationMessagesView(APIView):
    def get(self, request, conversation_id):
        conversation = _conversation_for_user(request.user, conversation_id)
        try:
            limit = max(1, min(int(request.query_params.get("limit", 50)), 100))
        except (TypeError, ValueError) as exc:
            raise ValidationError({"limit": "limit must be an integer."}) from exc

        query = (
            Message.objects.filter(conversation=conversation)
            .select_related(
                "sender",
                "conversation__buyer",
                "conversation__seller__user",
                "attachment__upload",
            )
            .prefetch_related("attachment__upload__variants")
            .order_by("-created_at", "-id")
        )
        before_raw = request.query_params.get("before")
        before_id = request.query_params.get("beforeId")
        if before_raw:
            before = parse_datetime(before_raw)
            if before is None:
                raise ValidationError({"before": "Use an ISO-8601 datetime."})
            boundary = Q(created_at__lt=before)
            if before_id:
                boundary |= Q(created_at=before, id__lt=str(before_id))
            query = query.filter(boundary)

        items = list(query[:limit])
        items.reverse()
        return Response(
            {"results": [serialize_message(item, request.user) for item in items]}
        )

    def post(self, request, conversation_id):
        conversation = _conversation_for_user(request.user, conversation_id)
        text = request.data.get("text") or ""
        if not isinstance(text, str):
            raise ValidationError({"text": "text must be a string."})

        upload = None
        upload_id = request.data.get("uploadId")
        if upload_id:
            try:
                upload = UploadAsset.objects.get(pk=str(upload_id))
            except (UploadAsset.DoesNotExist, ValueError) as exc:
                raise NotFound("Upload not found.") from exc

        try:
            message = send_message(
                user=request.user,
                conversation=conversation,
                text=text,
                upload=upload,
            )
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            _raise_service_error(exc)

        message = (
            Message.objects.select_related(
                "sender",
                "conversation__buyer",
                "conversation__seller__user",
                "attachment__upload",
            )
            .prefetch_related("attachment__upload__variants")
            .get(pk=message.pk)
        )
        return Response(serialize_message(message, request.user), status=201)


class ConversationReadView(APIView):
    def post(self, request, conversation_id):
        conversation = _conversation_for_user(request.user, conversation_id)
        try:
            mark_conversation_read(user=request.user, conversation=conversation)
        except (DjangoValidationError, DjangoPermissionDenied) as exc:
            _raise_service_error(exc)
        return Response({"read": True})


class MessagingCountsView(APIView):
    def get(self, request):
        return Response(
            {
                "unreadMessageCount": unread_message_count(request.user),
                "unreadNotificationCount": unread_notification_count(request.user),
            }
        )
