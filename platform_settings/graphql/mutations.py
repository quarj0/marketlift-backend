import strawberry
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.db import transaction

from audit.services import record_audit_event
from marketlift.graphql.auth import request_from_info, require_staff
from marketlift.graphql.errors import validation_error
from platform_settings.models import PlatformConfiguration

from .mappers import config_to_type
from .types import PlatformConfigurationInput, PlatformConfigurationType

_EDITABLE_FIELDS = (
    "marketplace_name",
    "support_email",
    "allow_new_registrations",
    "allow_seller_activation",
    "maintenance_mode",
    "automated_listing_flagging",
    "seller_verification_required",
    "default_listing_duration_days",
    "max_listing_images",
    "high_risk_threshold",
    "admin_email_operational_alerts",
    "admin_verification_queue_alerts",
    "admin_payment_failure_alerts",
    "feature_flags",
)


@strawberry.type
class PlatformSettingsMutation:
    @strawberry.mutation
    def update_platform_configuration(
        self,
        info: strawberry.Info,
        input: PlatformConfigurationInput,
    ) -> PlatformConfigurationType:
        staff = require_staff(info, roles={"admin"})
        config = PlatformConfiguration.load()
        before = {field: getattr(config, field) for field in _EDITABLE_FIELDS}

        for field in _EDITABLE_FIELDS:
            value = getattr(input, field)
            if value is not None:
                setattr(config, field, value)

        try:
            if not 1 <= config.default_listing_duration_days <= 3650:
                raise ValidationError(
                    "Listing duration must be between 1 and 3650 days."
                )
            if not 1 <= config.max_listing_images <= 50:
                raise ValidationError(
                    "Maximum listing images must be between 1 and 50."
                )
            if not 0 <= config.high_risk_threshold <= 100:
                raise ValidationError("High-risk threshold must be between 0 and 100.")
            config.full_clean(exclude=("id", "singleton_key"))
        except ValidationError as exc:
            raise validation_error(exc)

        config.save()
        try:
            from django.core.cache import cache

            cache.delete("ml:platform:maintenance")
        except Exception:
            pass
        changed = {
            field: {"before": before[field], "after": getattr(config, field)}
            for field in _EDITABLE_FIELDS
            if before[field] != getattr(config, field)
        }
        record_audit_event(
            actor=staff,
            action="settings.updated",
            target=config,
            target_type="platform_settings",
            target_label="Platform configuration",
            metadata={"changed": changed},
            request=request_from_info(info),
        )
        return config_to_type(config)

    @strawberry.mutation
    @transaction.atomic
    def invalidate_all_sessions(self, info: strawberry.Info, reason: str) -> int:
        staff = require_staff(info, roles={"admin"})
        reason = (reason or "").strip()
        if not reason:
            raise validation_error(ValidationError({"reason": "A reason is required."}))

        count = Session.objects.count()
        Session.objects.all().delete()
        record_audit_event(
            actor=staff,
            action="security.sessions_invalidated",
            target=PlatformConfiguration.load(),
            target_type="platform_settings",
            target_label="All sessions",
            metadata={"reason": reason, "invalidatedSessions": count},
            request=request_from_info(info),
        )
        return count
