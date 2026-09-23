from django.urls import path

from .views import (
    ConversationCollectionView,
    ConversationDetailView,
    ConversationMessagesView,
    ConversationReadView,
    MessagingCountsView,
)

urlpatterns = [
    path("conversations/", ConversationCollectionView.as_view(), name="messaging-conversations"),
    path("conversations/<uuid:conversation_id>/", ConversationDetailView.as_view(), name="messaging-conversation"),
    path("conversations/<uuid:conversation_id>/messages/", ConversationMessagesView.as_view(), name="messaging-messages"),
    path("conversations/<uuid:conversation_id>/read/", ConversationReadView.as_view(), name="messaging-read"),
    path("counts/", MessagingCountsView.as_view(), name="messaging-counts"),
]
