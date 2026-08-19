from django.apps import AppConfig


class MarketliftSecurityConfig(AppConfig):
    name = "marketlift.security"
    label = "marketlift_security"
    verbose_name = "Marketlift security"

    def ready(self):
        from . import checks  # noqa: F401
