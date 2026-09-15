from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.decorators.cache import never_cache
from commerce.webhooks import pagarme_webhook
from marketlift.api.views import market_profile
from marketlift.graphql.schema import schema
from marketlift.graphql.views import MarketliftGraphQLView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Canonical public API remains versioned under /api/v1/. Keep the older
    # market-capabilities URL as a compatibility alias so deployed clients do
    # not receive a 404 during the multi-market migration.
    path("api/market/", market_profile, name="market-profile-compat"),
    path(
        "api/v1/webhooks/pagarme/<str:token>/", pagarme_webhook, name="pagarme-webhook"
    ),
    path("api/v1/", include("marketlift.api.urls")),
    path(
        "graphql/",
        never_cache(
            MarketliftGraphQLView.as_view(
                schema=schema,
                graphql_ide=(
                    "graphiql" if settings.MARKETLIFT_GRAPHQL_IDE_ENABLED else None
                ),
                # Public server-rendered frontend queries use GET. Strawberry still
                # rejects mutations over GET; POST mutations retain CSRF protection.
                allow_queries_via_get=True,
            )
        ),
        name="graphql",
    ),
]
