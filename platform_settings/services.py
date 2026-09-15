from importlib import import_module

from django.conf import settings
from django.contrib.sessions.models import Session

from .models import PlatformConfiguration


def get_platform_configuration():
    return PlatformConfiguration.load()


def invalidate_all_sessions() -> int:
    """Delete every active session from both its database and cache storage.

    Marketlift uses Django's ``cached_db`` session backend in production. Bulk
    deleting ``django_session`` rows leaves the Redis copies alive, which means
    browsers can keep loading a stale authenticated session and later hit an
    ``UpdateError`` when Django tries to save it. Deleting through the configured
    session backend keeps every layer in sync.
    """

    session_keys = list(Session.objects.values_list("session_key", flat=True))
    session_store = import_module(settings.SESSION_ENGINE).SessionStore
    for session_key in session_keys:
        session_store(session_key=session_key).delete(session_key)
    return len(session_keys)
