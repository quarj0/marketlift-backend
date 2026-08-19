"""GraphQL domain registry.

This module contains only schema composition imports/tuples. Resolvers, inputs and
API types stay inside their owning Django apps.
"""

from accounts.graphql.mutations import AccountMutation
from accounts.graphql.queries import AccountQuery
from audit.graphql.queries import AuditQuery
from categories.graphql.mutations import CategoryMutation
from categories.graphql.queries import CategoryQuery
from listings.graphql.mutations import ListingMutation
from listings.graphql.queries import ListingQuery
from marketplace_analytics.queries import AnalyticsQuery
from messaging.graphql.mutations import MessagingMutation
from messaging.graphql.queries import MessagingQuery
from moderation.graphql.mutations import ModerationMutation
from moderation.graphql.queries import ModerationQuery
from notifications.graphql.mutations import NotificationMutation
from notifications.graphql.queries import NotificationQuery
from payments.graphql.mutations import PaymentMutation
from payments.graphql.queries import PaymentQuery
from platform_settings.graphql.mutations import PlatformSettingsMutation
from platform_settings.graphql.queries import PlatformSettingsQuery
from promotions.graphql.mutations import PromotionMutation
from promotions.graphql.queries import PromotionQuery
from reports.graphql.mutations import ReportMutation
from reports.graphql.queries import ReportQuery
from reviews.graphql.mutations import ReviewMutation
from reviews.graphql.queries import ReviewQuery
from saved_searches.graphql.mutations import SavedSearchMutation
from saved_searches.graphql.queries import SavedSearchQuery
from sellers.graphql.mutations import SellerMutation
from sellers.graphql.queries import SellerQuery
from subscriptions.graphql.mutations import SubscriptionMutation
from subscriptions.graphql.queries import SubscriptionQuery
from support.graphql.mutations import SupportMutation
from support.graphql.queries import SupportQuery
from verifications.graphql.mutations import VerificationMutation
from verifications.graphql.queries import VerificationQuery

from .queries import HealthQuery

QUERY_TYPES = (
    HealthQuery,
    AccountQuery,
    SellerQuery,
    CategoryQuery,
    ListingQuery,
    SubscriptionQuery,
    PromotionQuery,
    PaymentQuery,
    VerificationQuery,
    ModerationQuery,
    ReportQuery,
    NotificationQuery,
    AuditQuery,
    MessagingQuery,
    ReviewQuery,
    SavedSearchQuery,
    SupportQuery,
    PlatformSettingsQuery,
    AnalyticsQuery,
)

MUTATION_TYPES = (
    AccountMutation,
    SellerMutation,
    CategoryMutation,
    ListingMutation,
    SubscriptionMutation,
    PromotionMutation,
    PaymentMutation,
    VerificationMutation,
    ModerationMutation,
    ReportMutation,
    NotificationMutation,
    MessagingMutation,
    ReviewMutation,
    SavedSearchMutation,
    SupportMutation,
    PlatformSettingsMutation,
)
