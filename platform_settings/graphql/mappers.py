from platform_settings.models import PlatformConfiguration

from .types import PlatformConfigurationType


def config_to_type(config: PlatformConfiguration) -> PlatformConfigurationType:
    return PlatformConfigurationType(
        marketplace_name=config.marketplace_name,
        support_email=config.support_email,
        allow_new_registrations=config.allow_new_registrations,
        allow_seller_activation=config.allow_seller_activation,
        maintenance_mode=config.maintenance_mode,
        automated_listing_flagging=config.automated_listing_flagging,
        seller_verification_required=config.seller_verification_required,
        default_listing_duration_days=config.default_listing_duration_days,
        max_listing_images=config.max_listing_images,
        high_risk_threshold=config.high_risk_threshold,
        admin_email_operational_alerts=config.admin_email_operational_alerts,
        admin_verification_queue_alerts=config.admin_verification_queue_alerts,
        admin_payment_failure_alerts=config.admin_payment_failure_alerts,
        feature_flags=config.feature_flags,
    )
