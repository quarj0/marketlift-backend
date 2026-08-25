import strawberry
from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.db import transaction

from audit.services import record_audit_event
from marketlift.graphql.auth import request_from_info, require_staff
from marketlift.graphql.errors import not_found_error, validation_error
from marketlift.markets.profiles import get_market_profile
from payments.models import Payment
from platform_settings.models import (
    Market,
    PlatformConfiguration,
    PromotionProductMarketPrice,
    SellerPlanMarketPrice,
)
from promotions.models import PromotionProduct
from subscriptions.models import SellerPlan

from .mappers import (
    config_to_type,
    market_to_type,
    promotion_market_price_to_type,
    seller_plan_market_price_to_type,
)
from .types import (
    MarketConfigurationInput,
    MarketType,
    PlatformConfigurationInput,
    PlatformConfigurationType,
    PromotionMarketPriceType,
    SellerPlanMarketPriceType,
)

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


def _market_or_error(code: str) -> Market:
    try:
        return Market.objects.get(code=(code or "").strip().upper())
    except Market.DoesNotExist as exc:
        raise not_found_error("Market", code="MARKET_NOT_FOUND") from exc


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

        if not settings.MARKETLIFT_IDENTITY_VERIFICATION_ENABLED:
            config.seller_verification_required = False
            config.admin_verification_queue_alerts = False
        if not settings.MARKETLIFT_PAYMENTS_ENABLED:
            config.admin_payment_failure_alerts = False

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
            raise validation_error(exc, code="PLATFORM_SETTINGS_VALIDATION_ERROR")

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
    def update_market(
        self,
        info: strawberry.Info,
        code: str,
        input: MarketConfigurationInput,
    ) -> MarketType:
        staff = require_staff(info, roles={"admin"})
        market = _market_or_error(code)
        before = {
            "is_enabled": market.is_enabled,
            "is_default": market.is_default,
            "payment_provider": market.payment_provider,
            "payment_methods": list(market.payment_methods or []),
            "identity_provider": market.identity_provider,
            "sort_order": market.sort_order,
        }

        base_profile = get_market_profile(market.code)
        if input.payment_provider is not None:
            provider = input.payment_provider.strip().lower()
            allowed_providers = {
                "disabled",
                "mock",
                base_profile.default_payment_provider,
            }
            if provider not in allowed_providers:
                raise validation_error(
                    ValidationError(
                        {
                            "paymentProvider": (
                                f"{provider!r} is not configured for {market.country_name}. "
                                f"Allowed: {', '.join(sorted(allowed_providers))}."
                            )
                        }
                    ),
                    code="MARKET_VALIDATION_ERROR",
                )
            market.payment_provider = provider
        if input.payment_methods is not None:
            country_methods = set(base_profile.payment_methods)
            methods = list(
                dict.fromkeys(
                    x.strip().lower() for x in input.payment_methods if x.strip()
                )
            )
            invalid = sorted(set(methods) - country_methods)
            if invalid:
                raise validation_error(
                    ValidationError(
                        {
                            "paymentMethods": (
                                f"Unsupported for {market.country_name}: {', '.join(invalid)}."
                            )
                        }
                    ),
                    code="MARKET_VALIDATION_ERROR",
                )
            market.payment_methods = methods
        if input.identity_provider is not None:
            market.identity_provider = (
                input.identity_provider.strip().lower() or "disabled"
            )
        if input.sort_order is not None:
            market.sort_order = max(0, input.sort_order)
        if input.is_enabled is not None:
            if market.is_default and not input.is_enabled:
                raise validation_error(
                    ValidationError(
                        {
                            "isEnabled": "Choose another default market before disabling this one."
                        }
                    ),
                    code="MARKET_VALIDATION_ERROR",
                )
            market.is_enabled = input.is_enabled
        if input.is_default is not None:
            if market.is_default and not input.is_default:
                raise validation_error(
                    ValidationError(
                        {
                            "isDefault": "Set another enabled market as default instead of clearing the current default."
                        }
                    ),
                    code="MARKET_VALIDATION_ERROR",
                )
            market.is_default = input.is_default
            if input.is_default:
                market.is_enabled = True

        try:
            market.full_clean(exclude=("id",))
            market.save()
        except ValidationError as exc:
            raise validation_error(exc, code="MARKET_VALIDATION_ERROR") from exc

        after = {
            "is_enabled": market.is_enabled,
            "is_default": market.is_default,
            "payment_provider": market.payment_provider,
            "payment_methods": list(market.payment_methods or []),
            "identity_provider": market.identity_provider,
            "sort_order": market.sort_order,
        }
        record_audit_event(
            actor=staff,
            action="market.updated",
            target=market,
            target_type="market",
            target_label=f"{market.country_name} ({market.code})",
            metadata={"before": before, "after": after},
            request=request_from_info(info),
        )
        return market_to_type(market)

    @strawberry.mutation
    @transaction.atomic
    def set_seller_plan_market_price(
        self,
        info: strawberry.Info,
        market_code: str,
        plan_id: str,
        monthly_price: float,
        yearly_price: float,
        active: bool = True,
    ) -> SellerPlanMarketPriceType:
        staff = require_staff(info, roles={"admin", "finance"})
        market = _market_or_error(market_code)
        try:
            plan = SellerPlan.objects.get(code=plan_id)
        except SellerPlan.DoesNotExist as exc:
            raise not_found_error("Seller plan", code="SELLER_PLAN_NOT_FOUND") from exc
        if monthly_price < 0 or yearly_price < 0:
            raise validation_error(
                ValidationError("Market prices cannot be negative."),
                code="MARKET_PRICE_VALIDATION_ERROR",
            )
        row, _ = SellerPlanMarketPrice.objects.update_or_create(
            market=market,
            plan=plan,
            defaults={
                "monthly_price": monthly_price,
                "yearly_price": yearly_price,
                "active": active,
            },
        )
        record_audit_event(
            actor=staff,
            action="market.plan_price.updated",
            target=row,
            target_type="seller_plan_market_price",
            target_label=f"{market.code} · {plan.code}",
            metadata={
                "monthly": str(row.monthly_price),
                "yearly": str(row.yearly_price),
                "active": row.active,
            },
            request=request_from_info(info),
        )
        return seller_plan_market_price_to_type(row)

    @strawberry.mutation
    @transaction.atomic
    def set_promotion_market_price(
        self,
        info: strawberry.Info,
        market_code: str,
        promotion_id: str,
        price: float,
        active: bool = True,
    ) -> PromotionMarketPriceType:
        staff = require_staff(info, roles={"admin", "finance"})
        market = _market_or_error(market_code)
        try:
            product = PromotionProduct.objects.get(code=promotion_id)
        except PromotionProduct.DoesNotExist as exc:
            raise not_found_error("Promotion", code="PROMOTION_NOT_FOUND") from exc
        if price < 0:
            raise validation_error(
                ValidationError("Market price cannot be negative."),
                code="MARKET_PRICE_VALIDATION_ERROR",
            )
        row, _ = PromotionProductMarketPrice.objects.update_or_create(
            market=market,
            product=product,
            defaults={"price": price, "active": active},
        )
        record_audit_event(
            actor=staff,
            action="market.promotion_price.updated",
            target=row,
            target_type="promotion_market_price",
            target_label=f"{market.code} · {product.code}",
            metadata={"price": str(row.price), "active": row.active},
            request=request_from_info(info),
        )
        return promotion_market_price_to_type(row)

    @strawberry.mutation
    @transaction.atomic
    def invalidate_all_sessions(self, info: strawberry.Info, reason: str) -> int:
        staff = require_staff(info, roles={"admin"})
        reason = (reason or "").strip()
        if not reason:
            raise validation_error(
                ValidationError({"reason": "A reason is required."}),
                code="PLATFORM_SETTINGS_VALIDATION_ERROR",
            )

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
