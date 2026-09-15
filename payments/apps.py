from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payments"

    def import_models(self):
        super().import_models()
        from . import commerce_models  # noqa: F401
        from . import delivery_models  # noqa: F401

    def ready(self):
        # Standalone Celery workers/beat load installed Django apps even when no
        # GraphQL or webhook module imports the commerce package. Importing the
        # package here guarantees its settlement-release beat entry is registered.
        import commerce  # noqa: F401
