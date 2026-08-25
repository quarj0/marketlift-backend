from django.apps import AppConfig
from django.db.models.signals import post_migrate


class PlatformSettingsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "platform_settings"

    def ready(self):
        post_migrate.connect(
            _restore_market_catalog,
            sender=self,
            dispatch_uid="marketlift.platform_settings.restore_market_catalog",
            weak=False,
        )


def _restore_market_catalog(*, using="default", **kwargs):
    # ``flush`` emits post_migrate too. This is intentional: with --keepdb a
    # TransactionTestCase may clear reference rows while preserving migration
    # history, and the catalog must be restored before later tests/requests.
    from platform_settings.market_catalog import ensure_market_catalog

    ensure_market_catalog(using=using)
