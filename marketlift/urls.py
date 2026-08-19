from django.contrib import admin
from django.urls import include, path
from strawberry.django.views import GraphQLView

from marketlift.graphql.schema import schema

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("marketlift.api.urls")),
    path("graphql/", GraphQLView.as_view(schema=schema), name="graphql"),
]
