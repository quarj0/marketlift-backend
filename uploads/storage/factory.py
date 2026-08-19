from functools import lru_cache

from django.conf import settings
from django.utils.module_loading import import_string


@lru_cache(maxsize=4)
def get_storage_backend(alias: str = "default"):
    backends = getattr(settings, "MARKETLIFT_STORAGE_BACKENDS", {})
    dotted_path = backends.get(alias)
    if not dotted_path:
        raise RuntimeError(f"Storage backend alias '{alias}' is not configured.")
    backend_class = import_string(dotted_path)
    return backend_class()
