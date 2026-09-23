import io

from PIL import Image

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import AccountSettings
from categories.models import Category
from listings.models import Listing
from messaging.graphql.mappers import conversation_to_type
from messaging.models import Conversation, UserBlock
from messaging.services import (
    block_conversation_user,
    mark_conversation_read,
    send_message,
    start_conversation,
)
from sellers.models import SellerProfile, SellerSettings
from uploads.models import UploadAsset
from uploads.services import complete_upload, prepare_upload, store_proxy_upload

User = get_user_model()


@override_settings(
    MARKETLIFT_STORAGE_BACKENDS={
        "default": "uploads.storage.local.LocalStorageBackend"
    },
    MARKETLIFT_UPLOAD_STAGING_ALIAS="default",
    MARKETLIFT_UPLOAD_PURPOSE_ALIASES={"message_image": "default"},
    MARKETLIFT_LOCAL_UPLOAD_ROOT="/tmp/marketlift-message-test-uploads",
)
class MessagingServiceTests(TestCase):
    def setUp(self):
        self.buyer = User.objects.create_user(
            email="buyer@example.com", full_name="Buyer", password="secret123"
        )
        self.seller_user = User.objects.create_user(
            email="seller@example.com", full_name="Seller", password="secret123"
        )
        self.seller = SellerProfile.objects.create(
            user=self.seller_user, display_name="Seller"
        )
        self.category = Category.objects.create(
            slug="test", name="Test", active=True, pricing_mode="optional"
        )
        self.listing = Listing.objects.create(
            seller=self.seller,
            category=self.category,
            title="Test listing",
            description="Description",
            state="State",
            state_code="ST",
            city="City",
            status=Listing.Status.PUBLISHED,
        )

    def test_one_conversation_per_buyer_listing(self):
        first = start_conversation(buyer=self.buyer, listing=self.listing)
        second = start_conversation(buyer=self.buyer, listing=self.listing)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Conversation.objects.count(), 1)

    def test_unread_and_read_receipts(self):
        conversation = start_conversation(buyer=self.buyer, listing=self.listing)
        message = send_message(user=self.buyer, conversation=conversation, text="Hello")
        conversation.refresh_from_db()
        self.assertEqual(conversation.unread_count_for(self.seller_user), 1)
        mark_conversation_read(user=self.seller_user, conversation=conversation)
        conversation.refresh_from_db()
        self.assertEqual(conversation.unread_count_for(self.seller_user), 0)

    def test_image_attachment_claims_upload(self):
        conversation = start_conversation(buyer=self.buyer, listing=self.listing)
        buffer = io.BytesIO()
        Image.new("RGB", (2, 2), "white").save(buffer, format="JPEG")
        payload = buffer.getvalue()
        asset, _ = prepare_upload(
            user=self.buyer,
            purpose=UploadAsset.Purpose.MESSAGE_IMAGE,
            original_name="photo.jpg",
            mime_type="image/jpeg",
            size=len(payload),
        )
        store_proxy_upload(
            asset=asset,
            user=self.buyer,
            stream=io.BytesIO(payload),
            content_type="image/jpeg",
            content_length=len(payload),
        )
        complete_upload(asset=asset, user=self.buyer)
        message = send_message(user=self.buyer, conversation=conversation, upload=asset)
        asset.refresh_from_db()
        self.assertTrue(hasattr(message, "attachment"))
        self.assertEqual(asset.status, UploadAsset.Status.ATTACHED)

    def test_graphql_start_conversation_returns_empty_thread(self):
        self.client.force_login(self.buyer)
        response = self.client.post(
            "/graphql/",
            data={
                "query": """
                    mutation StartConversation($listingId: ID!) {
                      startConversation(listingId: $listingId) {
                        id
                        participant { id name verifiedSeller isSeller phone online }
                        listing { id slug title price primaryImage status deleted countryCode state stateCode city district }
                        lastMessage
                        lastMessageAt
                        unread
                        archived
                        blocked
                      }
                    }
                """,
                "variables": {"listingId": str(self.listing.id)},
            },
            content_type="application/json",
        )
        payload = response.json()
        self.assertNotIn("errors", payload)
        conversation = payload["data"]["startConversation"]
        self.assertEqual(conversation["listing"]["id"], str(self.listing.id))
        self.assertEqual(conversation["lastMessage"], "")
        self.assertIsNone(conversation["lastMessageAt"])

        inbox = self.client.post(
            "/graphql/",
            data={
                "query": """
                    query Inbox {
                      myConversations {
                        id
                        lastMessage
                        lastMessageAt
                      }
                    }
                """
            },
            content_type="application/json",
        ).json()
        self.assertNotIn("errors", inbox)
        self.assertEqual(len(inbox["data"]["myConversations"]), 1)
        self.assertEqual(
            inbox["data"]["myConversations"][0]["id"],
            conversation["id"],
        )

    def test_graphql_send_message_returns_created_message(self):
        conversation = start_conversation(buyer=self.buyer, listing=self.listing)
        self.client.force_login(self.buyer)
        response = self.client.post(
            "/graphql/",
            data={
                "query": """
                    mutation SendMessage($input: SendMessageInput!) {
                      sendMessage(input: $input) {
                        id
                        conversationId
                        text
                      }
                    }
                """,
                "variables": {
                    "input": {
                        "conversationId": str(conversation.id),
                        "text": "Would you consider R$ 300?",
                    }
                },
            },
            content_type="application/json",
        )
        payload = response.json()
        self.assertNotIn("errors", payload)
        self.assertEqual(
            payload["data"]["sendMessage"]["conversationId"],
            str(conversation.id),
        )
        self.assertEqual(
            payload["data"]["sendMessage"]["text"],
            "Would you consider R$ 300?",
        )

    def test_block_prevents_messages(self):
        conversation = start_conversation(buyer=self.buyer, listing=self.listing)
        block_conversation_user(user=self.buyer, conversation=conversation)
        self.assertTrue(
            UserBlock.objects.filter(
                blocker=self.buyer, blocked=self.seller_user
            ).exists()
        )
        with self.assertRaisesMessage(Exception, "blocked"):
            send_message(user=self.seller_user, conversation=conversation, text="Hello")

    def test_removed_listing_closes_writes(self):
        conversation = start_conversation(buyer=self.buyer, listing=self.listing)
        self.listing.status = Listing.Status.REMOVED
        self.listing.save(update_fields=("status", "updated_at"))
        with self.assertRaisesMessage(Exception, "closed"):
            send_message(user=self.buyer, conversation=conversation, text="Hello")

    def test_removed_listing_is_hidden_from_conversation_context(self):
        conversation = start_conversation(buyer=self.buyer, listing=self.listing)
        self.listing.status = Listing.Status.REMOVED
        self.listing.save(update_fields=("status", "updated_at"))
        conversation.refresh_from_db()
        payload = conversation_to_type(conversation, self.buyer)
        self.assertTrue(payload.listing.deleted)

    def test_seller_deleted_listing_is_hidden_from_conversation_context(self):
        conversation = start_conversation(buyer=self.buyer, listing=self.listing)
        self.listing.seller_deleted_at = timezone.now()
        self.listing.save(update_fields=("seller_deleted_at", "updated_at"))
        conversation.refresh_from_db()
        payload = conversation_to_type(conversation, self.buyer)
        self.assertTrue(payload.listing.deleted)

    def test_buyer_phone_is_private_to_seller_by_default(self):
        self.buyer.phone = "+233200000001"
        self.buyer.save(update_fields=("phone", "updated_at"))
        conversation = start_conversation(buyer=self.buyer, listing=self.listing)

        payload = conversation_to_type(conversation, self.seller_user)

        self.assertIsNone(payload.participant.phone)

    def test_buyer_can_share_phone_with_contacted_seller(self):
        self.buyer.phone = "+233200000001"
        self.buyer.save(update_fields=("phone", "updated_at"))
        AccountSettings.objects.create(
            user=self.buyer,
            show_phone_to_sellers=True,
        )
        conversation = start_conversation(buyer=self.buyer, listing=self.listing)

        payload = conversation_to_type(conversation, self.seller_user)

        self.assertEqual(payload.participant.phone, self.buyer.phone)

    def test_seller_phone_respects_storefront_setting(self):
        self.seller_user.phone = "+233200000002"
        self.seller_user.save(update_fields=("phone", "updated_at"))
        seller_settings = SellerSettings.objects.create(
            user_profile=self.seller,
            show_phone=False,
        )
        conversation = start_conversation(buyer=self.buyer, listing=self.listing)

        hidden = conversation_to_type(conversation, self.buyer)
        self.assertIsNone(hidden.participant.phone)

        seller_settings.show_phone = True
        seller_settings.save(update_fields=("show_phone", "updated_at"))
        visible = conversation_to_type(conversation, self.buyer)
        self.assertEqual(visible.participant.phone, self.seller_user.phone)

    def test_online_presence_respects_account_privacy(self):
        settings = AccountSettings.objects.create(
            user=self.buyer,
            show_online_status=True,
        )
        cache.set(f"ml:presence:{self.buyer.pk}", True, timeout=75)
        conversation = start_conversation(buyer=self.buyer, listing=self.listing)

        visible = conversation_to_type(conversation, self.seller_user)
        self.assertTrue(visible.participant.online)

        settings.show_online_status = False
        settings.save(update_fields=("show_online_status", "updated_at"))
        hidden = conversation_to_type(conversation, self.seller_user)
        self.assertFalse(hidden.participant.online)

    def test_received_message_can_be_reported(self):
        from reports.models import Report
        from reports.services import create_report

        conversation = start_conversation(buyer=self.buyer, listing=self.listing)
        message = send_message(
            user=self.seller_user, conversation=conversation, text="Suspicious request"
        )
        report = create_report(
            reporter=self.buyer,
            target_type=Report.TargetType.MESSAGE,
            target_id=message.id,
            reason=Report.Reason.SAFETY,
            statement="This message looks unsafe.",
        )
        self.assertEqual(report.message_id, message.id)
        self.assertEqual(report.target_type, Report.TargetType.MESSAGE)
