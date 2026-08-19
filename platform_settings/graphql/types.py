import strawberry
from strawberry.scalars import JSON


@strawberry.type
class PlatformConfigurationType:
    marketplace_name: str
    support_email: str
    allow_new_registrations: bool
    allow_seller_activation: bool
    maintenance_mode: bool
    automated_listing_flagging: bool
    seller_verification_required: bool
    default_listing_duration_days: int
    max_listing_images: int
    high_risk_threshold: int
    admin_email_operational_alerts: bool
    admin_verification_queue_alerts: bool
    admin_payment_failure_alerts: bool
    feature_flags: JSON


@strawberry.input
class PlatformConfigurationInput:
    marketplace_name: str | None = None
    support_email: str | None = None
    allow_new_registrations: bool | None = None
    allow_seller_activation: bool | None = None
    maintenance_mode: bool | None = None
    automated_listing_flagging: bool | None = None
    seller_verification_required: bool | None = None
    default_listing_duration_days: int | None = None
    max_listing_images: int | None = None
    high_risk_threshold: int | None = None
    admin_email_operational_alerts: bool | None = None
    admin_verification_queue_alerts: bool | None = None
    admin_payment_failure_alerts: bool | None = None
    feature_flags: JSON | None = None
