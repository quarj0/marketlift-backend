from django.apps import AppConfig


class CommerceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "commerce"

    def ready(self):
        # Policies live in a separate module to keep the financial models focused.
        from . import policy_models  # noqa: F401
