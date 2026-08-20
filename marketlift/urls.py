from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from marketlift.graphql.schema import schema
from marketlift.graphql.views import MarketliftGraphQLView

urlpatterns = [
    path("admin/", admin.site.urls),
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
