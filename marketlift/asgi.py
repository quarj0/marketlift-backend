"""ASGI entry point for HTTP and authenticated Marketlift realtime traffic."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "marketlift.settings")

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import OriginValidator
from django.conf import settings
from django.core.asgi import get_asgi_application

# Initialize Django before importing consumers that touch ORM models.
django_asgi_app = get_asgi_application()

from marketlift.realtime.routing import websocket_urlpatterns

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": OriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
            settings.MARKETLIFT_WEBSOCKET_ALLOWED_ORIGINS,
        ),
    }
)
