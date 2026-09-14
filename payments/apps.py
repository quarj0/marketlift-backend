from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payments"

    def import_models(self):
        super().import_models()
        from . import commerce_models  # noqa: F401
