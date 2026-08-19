import strawberry
from strawberry.tools import merge_types

from accounts.graphql.mutations import AccountMutation
from accounts.graphql.queries import AccountQuery
from audit.graphql.queries import AuditQuery
from categories.graphql.mutations import CategoryMutation
from categories.graphql.queries import CategoryQuery
from listings.graphql.mutations import ListingMutation
from listings.graphql.queries import ListingQuery
from marketlift.graphql.queries import HealthQuery
from moderation.graphql.mutations import ModerationMutation
from moderation.graphql.queries import ModerationQuery
from notifications.graphql.mutations import NotificationMutation
from notifications.graphql.queries import NotificationQuery
from payments.graphql.mutations import PaymentMutation
from payments.graphql.queries import PaymentQuery
from promotions.graphql.mutations import PromotionMutation
from promotions.graphql.queries import PromotionQuery
from reports.graphql.mutations import ReportMutation
from reports.graphql.queries import ReportQuery
from sellers.graphql.mutations import SellerMutation
from sellers.graphql.queries import SellerQuery
from subscriptions.graphql.mutations import SubscriptionMutation
from subscriptions.graphql.queries import SubscriptionQuery
from verifications.graphql.mutations import VerificationMutation
from verifications.graphql.queries import VerificationQuery

Query = merge_types(
    "Query",
    (
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
    ),
)
Mutation = merge_types(
    "Mutation",
    (
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
    ),
)

schema = strawberry.Schema(query=Query, mutation=Mutation)
