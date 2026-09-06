"""An authenticated activity download; private staff notes and credentials are excluded."""

import json
from django.core.serializers.json import DjangoJSONEncoder
from django.http import StreamingHttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from marketlift.security.rate_limit import enforce_rate_limit
from accounts.models import User, AccountSettings
from listings.models import Listing, SavedListing
from messaging.models import Message
from support.models import SupportTicket, SupportMessage
from reports.models import Report
from reviews.models import SellerReview


def export_sources(user_id):
    return [
        (
            "profile",
            User.objects.filter(pk=user_id).values(
                "id",
                "email",
                "full_name",
                "phone",
                "bio",
                "country_code",
                "state",
                "city",
                "district",
                "date_joined",
            ),
        ),
        (
            "preferences",
            AccountSettings.objects.filter(user_id=user_id).values(
                "language",
                "currency",
                "email_messages",
                "email_listing_updates",
                "email_recommendations",
                "marketing_emails",
                "show_phone_to_sellers",
                "show_online_status",
            ),
        ),
        (
            "listing",
            Listing.objects.filter(seller__user_id=user_id).values(
                "id",
                "slug",
                "title",
                "description",
                "price",
                "status",
                "created_at",
                "updated_at",
            ),
        ),
        (
            "saved_listing",
            SavedListing.objects.filter(user_id=user_id).values(
                "listing_id", "created_at"
            ),
        ),
        (
            "sent_message",
            Message.objects.filter(sender_id=user_id).values(
                "id", "conversation_id", "text", "created_at"
            ),
        ),
        (
            "support_ticket",
            SupportTicket.objects.filter(user_id=user_id).values(
                "id", "reference", "subject", "category", "status", "created_at"
            ),
        ),
        (
            "support_message",
            SupportMessage.objects.filter(
                ticket__user_id=user_id, internal=False
            ).values("id", "ticket_id", "body", "created_at"),
        ),
        (
            "report",
            Report.objects.filter(reporter_id=user_id).values(
                "id", "reference", "reason", "statement", "status", "created_at"
            ),
        ),
        (
            "review",
            SellerReview.objects.filter(reviewer_id=user_id).values(
                "id", "seller_id", "rating", "comment", "created_at"
            ),
        ),
    ]


async def activity_stream(sources):
    yield json.dumps(
        {
            "type": "manifest",
            "version": 1,
            "contents": "Profile, preferences and marketplace activity. Request additional records or deletion through account support.",
        }
    ) + "\n"
    for kind, query in sources:
        async for row in query.aiterator(chunk_size=200):
            yield json.dumps(
                {"type": kind, "data": row}, cls=DjangoJSONEncoder, ensure_ascii=False
            ) + "\n"


class AccountActivityExportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        enforce_rate_limit(request, "account-activity-export", limit=3, window=3600)
        response = StreamingHttpResponse(
            activity_stream(export_sources(request.user.pk)),
            content_type="application/x-ndjson; charset=utf-8",
        )
        response["Content-Disposition"] = (
            'attachment; filename="marketlift-account-activity.ndjson"'
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
