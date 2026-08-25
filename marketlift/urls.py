from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from marketlift.api.views import market_profile
from marketlift.graphql.schema import schema
from marketlift.graphql.views import MarketliftGraphQLView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Canonical public API remains versioned under /api/v1/. Keep the older
    # market-capabilities URL as a compatibility alias so deployed clients do
    # not receive a 404 during the multi-market migration.
    path("api/market/", market_profile, name="market-profile-compat"),
    path("api/v1/", include("marketlift.api.urls")),
    path(
        "graphql/",
        MarketliftGraphQLView.as_view(
            schema=schema,
            graphql_ide="graphiql" if settings.MARKETLIFT_GRAPHQL_IDE_ENABLED else None,
            allow_queries_via_get=not settings.IS_PRODUCTION,
        ),
        name="graphql",
    ),
]
