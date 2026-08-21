from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.db import transaction, models
from django.utils import timezone

from categories.models import Category, CategoryField
from subscriptions.services import get_effective_plan
from uploads.models import UploadAsset
from uploads.services import claim_upload, retire_upload
from marketlift.location.tokens import decode_location_token
from marketlift.location.validators import (
    validate_coordinates,
    validate_location_strings,
)

from .models import Listing, ListingAttribute, ListingMedia

FINAL_STATUSES = {Listing.Status.REJECTED, Listing.Status.REMOVED}
PUBLISHABLE_STATUSES = {
    Listing.Status.DRAFT,
    Listing.Status.PAUSED,
    Listing.Status.EXPIRED,
}
ACTIVE_LIMIT_STATUSES = {Listing.Status.PUBLISHED, Listing.Status.UNDER_REVIEW}


def _resolve_listing_location(
    *,
    state: str = "",
    state_code: str = "",
    city: str = "",
    district: str = "",
    country_code: str = "BR",
    latitude=None,
    longitude=None,
    location_token: str | None = None,
) -> dict:
    if location_token:
        resolved = decode_location_token(location_token)
        strings = validate_location_strings(
            state=resolved["state"],
            state_code=resolved["state_code"],
            city=resolved["city"],
            district=resolved["district"],
            country_code=resolved["country_code"],
        )
        lat, lng = validate_coordinates(
            resolved["latitude"], resolved["longitude"], required=True
        )
        return {
            **strings,
            "location_point": Point(lng, lat, srid=4326),
            "location_provider": resolved["provider"],
            "location_provider_id": resolved["provider_id"],
        }

    if getattr(settings, "MARKETLIFT_REQUIRE_RESOLVED_LISTING_LOCATION", False):
        raise ValidationError(
            {"location_token": "Select one of the suggested locations."}
        )

    strings = validate_location_strings(
        state=state,
        state_code=state_code,
        city=city,
        district=district,
        country_code=country_code or "BR",
    )
    lat, lng = validate_coordinates(latitude, longitude)
    return {
        **strings,
        "location_point": Point(lng, lat, srid=4326) if lat is not None else None,
        "location_provider": "",
        "location_provider_id": "",
    }


def _validate_scalar(field: CategoryField, value):
    if field.field_type in {
        CategoryField.FieldType.TEXT,
        CategoryField.FieldType.TEXTAREA,
    }:
        if not isinstance(value, str):
            raise ValidationError({field.key: f"{field.label} must be text."})
        return value.strip()

    if field.field_type == CategoryField.FieldType.SELECT:
        if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
            raise ValidationError(
                {field.key: f"{field.label} must be a selected or typed value."}
            )
        candidate = str(value).strip()
        if not candidate:
            raise ValidationError({field.key: f"{field.label} cannot be empty."})

        # Normalize a typed option label/value back to the canonical option value.
        # Example: typing "Apple" stores "apple" when that option exists.
        options = list(field.options.values_list("value", "label"))
        candidate_folded = candidate.casefold()
        for option_value, option_label in options:
            if candidate_folded in {option_value.casefold(), option_label.casefold()}:
                return option_value

        if field.allow_custom_value:
            return candidate

        raise ValidationError({field.key: f"Invalid option for {field.label}."})

    if field.field_type == CategoryField.FieldType.BOOLEAN:
        if not isinstance(value, bool):
            raise ValidationError({field.key: f"{field.label} must be true or false."})
        return value

    if field.field_type == CategoryField.FieldType.NUMBER:
        if isinstance(value, bool):
            raise ValidationError({field.key: f"{field.label} must be a number."})
        try:
            number = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError({field.key: f"{field.label} must be a number."})
        if field.min_value is not None and number < field.min_value:
            raise ValidationError(
                {field.key: f"{field.label} must be at least {field.min_value}."}
            )
        if field.max_value is not None and number > field.max_value:
            raise ValidationError(
                {field.key: f"{field.label} must be at most {field.max_value}."}
            )
        return number

    raise ValidationError({field.key: f"Unsupported field type: {field.field_type}."})


def validate_listing_payload(
    *, category: Category, price, condition: str, attributes: dict | None
):
    errors: dict[str, str] = {}

    if category.pricing_mode == Category.PricingMode.REQUIRED and price is None:
        errors["price"] = "Price is required for this category."

    if category.condition_enabled:
        if category.condition_required and not condition:
            errors["condition"] = "Condition is required for this category."
        elif condition and condition not in Listing.Condition.values:
            errors["condition"] = "Invalid listing condition."
    elif condition:
        errors["condition"] = "Condition is disabled for this category."

    attributes = attributes or {}
    fields = list(category.fields.prefetch_related("options").all())
    known_keys = {field.key for field in fields}
    unknown = set(attributes) - known_keys
    if unknown:
        errors["attributes"] = f"Unknown category fields: {', '.join(sorted(unknown))}."

    normalized: dict[str, tuple[CategoryField, object]] = {}
    for field in fields:
        raw = attributes.get(field.key)
        if raw is None or raw == "":
            if field.required:
                errors[field.key] = f"{field.label} is required."
            continue
        try:
            normalized[field.key] = (field, _validate_scalar(field, raw))
        except ValidationError as exc:
            for key, messages in exc.message_dict.items():
                errors[key] = (
                    messages[0] if isinstance(messages, list) else str(messages)
                )

    if errors:
        raise ValidationError(errors)
    return normalized


def _write_attributes(
    listing: Listing, normalized: dict[str, tuple[CategoryField, object]]
):
    ListingAttribute.objects.filter(listing=listing).exclude(
        key__in=normalized.keys()
    ).delete()
    for key, (field, value) in normalized.items():
        defaults = {
            "field": field,
            "label_snapshot": field.label,
            "field_type_snapshot": field.field_type,
            "text_value": None,
            "number_value": None,
            "boolean_value": None,
        }
        if field.field_type == CategoryField.FieldType.NUMBER:
            defaults["number_value"] = value
        elif field.field_type == CategoryField.FieldType.BOOLEAN:
            defaults["boolean_value"] = value
        else:
            defaults["text_value"] = value
        ListingAttribute.objects.update_or_create(
            listing=listing,
            key=key,
            defaults=defaults,
        )


def _write_media(
    listing: Listing,
    *,
    owner,
    image_urls: list[str] | None,
    image_upload_ids: list | None,
):
    if image_urls is None and image_upload_ids is None:
        return

    current_uploads = [
        media.upload
        for media in listing.media.select_related("upload")
        if media.upload_id
    ]

    if image_upload_ids is not None:
        from platform_settings.services import get_platform_configuration

        max_images = get_platform_configuration().max_listing_images
        ordered_ids = [str(value) for value in image_upload_ids]
        if len(ordered_ids) > max_images:
            raise ValidationError(
                {"images": f"A listing can have at most {max_images} images."}
            )
        if len(set(ordered_ids)) != len(ordered_ids):
            raise ValidationError(
                {"images": "The same upload cannot be attached twice."}
            )
        assets = {
            str(asset.id): asset
            for asset in UploadAsset.objects.filter(id__in=ordered_ids)
        }
        if len(assets) != len(ordered_ids):
            raise ValidationError(
                {"images": "One or more image uploads were not found."}
            )
        current_ids = {str(item.id) for item in current_uploads}
        resolved = []
        for asset_id in ordered_ids:
            asset = assets[asset_id]
            if asset_id not in current_ids:
                asset = claim_upload(
                    asset=asset, user=owner, purpose=UploadAsset.Purpose.LISTING_IMAGE
                )
            elif asset.owner_id != owner.pk:
                raise ValidationError(
                    {"images": "A listing image belongs to another account."}
                )
            resolved.append(asset)

        listing.media.all().delete()
        ListingMedia.objects.bulk_create(
            [
                ListingMedia(
                    listing=listing,
                    upload=asset,
                    url=asset.content_url,
                    sort_order=index,
                    is_primary=index == 0,
                )
                for index, asset in enumerate(resolved)
            ]
        )
        retained_ids = {asset.id for asset in resolved}
        for old in current_uploads:
            if old.id not in retained_ids:
                retire_upload(asset=old)
        return

    # Backward-compatible external URL path while the frontend is migrated to
    # prepared upload IDs. It is intentionally separate from object storage.
    from platform_settings.services import get_platform_configuration

    max_images = get_platform_configuration().max_listing_images
    urls = [url for url in (image_urls or []) if url]
    if len(urls) > max_images:
        raise ValidationError(
            {"images": f"A listing can have at most {max_images} images."}
        )
    listing.media.all().delete()
    ListingMedia.objects.bulk_create(
        [
            ListingMedia(
                listing=listing, url=url, sort_order=index, is_primary=index == 0
            )
            for index, url in enumerate(urls)
        ]
    )
    for old in current_uploads:
        retire_upload(asset=old)


@transaction.atomic
def create_listing(
    *,
    seller,
    category: Category,
    title: str,
    description: str,
    price=None,
    condition: str = "",
    negotiable: bool = False,
    state: str = "",
    state_code: str = "",
    city: str = "",
    district: str = "",
    country_code: str = "BR",
    latitude=None,
    longitude=None,
    location_token: str | None = None,
    attributes: dict | None = None,
    image_urls: list[str] | None = None,
    image_upload_ids: list | None = None,
):
    if seller.is_suspended:
        raise ValidationError("Selling access is suspended.")
    if not category.active:
        raise ValidationError("This category is not accepting listings.")

    normalized = validate_listing_payload(
        category=category,
        price=price,
        condition=condition,
        attributes=attributes,
    )
    location = _resolve_listing_location(
        state=state,
        state_code=state_code,
        city=city,
        district=district,
        country_code=country_code,
        latitude=latitude,
        longitude=longitude,
        location_token=location_token,
    )
    listing = Listing.objects.create(
        seller=seller,
        category=category,
        title=title.strip(),
        description=description.strip(),
        price=price,
        condition=condition,
        negotiable=negotiable,
        state=location["state"],
        state_code=location["state_code"],
        city=location["city"],
        district=location["district"],
        country_code=location["country_code"],
        location_point=location["location_point"],
        location_provider=location["location_provider"],
        location_provider_id=location["location_provider_id"],
    )
    _write_attributes(listing, normalized)
    _write_media(
        listing,
        owner=seller.user,
        image_urls=image_urls,
        image_upload_ids=image_upload_ids,
    )
    return listing


@transaction.atomic
def update_listing(
    *,
    listing: Listing,
    category: Category,
    title: str,
    description: str,
    price=None,
    condition: str = "",
    negotiable: bool = False,
    state: str = "",
    state_code: str = "",
    city: str = "",
    district: str = "",
    country_code: str = "BR",
    latitude=None,
    longitude=None,
    location_token: str | None = None,
    attributes: dict | None = None,
    image_urls: list[str] | None = None,
    image_upload_ids: list | None = None,
):
    if listing.seller_deleted_at is not None:
        raise ValidationError("A deleted listing cannot be edited.")
    if listing.status in FINAL_STATUSES:
        raise ValidationError("A rejected or removed listing cannot be edited.")
    if listing.seller.is_suspended:
        raise ValidationError("Selling access is suspended.")
    if not category.active:
        raise ValidationError("This category is not accepting listings.")

    normalized = validate_listing_payload(
        category=category,
        price=price,
        condition=condition,
        attributes=attributes,
    )
    location = _resolve_listing_location(
        state=state,
        state_code=state_code,
        city=city,
        district=district,
        country_code=country_code,
        latitude=latitude,
        longitude=longitude,
        location_token=location_token,
    )
    listing.category = category
    listing.title = title.strip()
    listing.description = description.strip()
    listing.price = price
    listing.condition = condition
    listing.negotiable = negotiable
    listing.state = location["state"]
    listing.state_code = location["state_code"]
    listing.city = location["city"]
    listing.district = location["district"]
    listing.country_code = location["country_code"]
    listing.location_point = location["location_point"]
    listing.location_provider = location["location_provider"]
    listing.location_provider_id = location["location_provider_id"]
    listing.save()
    _write_attributes(listing, normalized)
    _write_media(
        listing,
        owner=listing.seller.user,
        image_urls=image_urls,
        image_upload_ids=image_upload_ids,
    )
    return listing


def enforce_listing_limit(seller, *, excluding_listing=None):
    plan = get_effective_plan(seller)
    if not plan:
        raise ValidationError("Seller plans have not been configured.")
    query = seller.listings.filter(status__in=ACTIVE_LIMIT_STATUSES)
    if excluding_listing is not None:
        query = query.exclude(pk=excluding_listing.pk)
    if query.count() >= plan.listing_limit:
        raise ValidationError(
            f"Your {plan.name} plan allows {plan.listing_limit} active listings."
        )
    return plan


@transaction.atomic
def publish_listing(listing: Listing):
    if listing.seller_deleted_at is not None:
        raise ValidationError("A deleted listing cannot be published.")
    if listing.seller.is_suspended:
        raise ValidationError("Selling access is suspended.")
    if listing.status == Listing.Status.PUBLISHED:
        return listing
    if listing.status not in PUBLISHABLE_STATUSES:
        raise ValidationError(
            f"Listing cannot be published from status '{listing.status}'."
        )
    if not listing.category_id or not listing.category.active:
        raise ValidationError("The listing category is unavailable.")

    # Re-validate persisted category-specific values before making the listing public.
    attributes = {item.key: item.value for item in listing.attribute_values.all()}
    validate_listing_payload(
        category=listing.category,
        price=listing.price,
        condition=listing.condition,
        attributes=attributes,
    )
    from datetime import timedelta
    from platform_settings.models import PlatformConfiguration

    config = PlatformConfiguration.load()
    if (
        settings.MARKETLIFT_CPF_VERIFICATION_ENABLED
        and config.seller_verification_required
        and not listing.seller.verified
    ):
        raise ValidationError(
            "Seller verification is required before publishing listings."
        )

    enforce_listing_limit(listing.seller, excluding_listing=listing)

    now = timezone.now()
    listing.status = Listing.Status.PUBLISHED
    listing.published_at = now
    listing.paused_at = None
    listing.expired_at = None
    listing.expires_at = now + timedelta(days=config.default_listing_duration_days)
    listing.save(
        update_fields=(
            "status",
            "published_at",
            "paused_at",
            "expired_at",
            "expires_at",
            "updated_at",
        )
    )
    return listing


@transaction.atomic
def pause_listing(listing: Listing):
    if listing.status != Listing.Status.PUBLISHED:
        raise ValidationError("Only a published listing can be paused.")
    listing.status = Listing.Status.PAUSED
    listing.paused_at = timezone.now()
    listing.save(update_fields=("status", "paused_at", "updated_at"))
    return listing


@transaction.atomic
def mark_listing_sold(listing: Listing):
    if listing.status not in {Listing.Status.PUBLISHED, Listing.Status.PAUSED}:
        raise ValidationError("Only a published or paused listing can be marked sold.")
    listing.status = Listing.Status.SOLD
    listing.sold_at = timezone.now()
    listing.save(update_fields=("status", "sold_at", "updated_at"))
    return listing


def record_listing_view(*, listing, user=None):
    Listing.objects.filter(pk=listing.pk).update(views=models.F("views") + 1)
    if user is not None and getattr(user, "is_authenticated", False):
        from .models import RecentlyViewedListing

        row, _ = RecentlyViewedListing.objects.get_or_create(user=user, listing=listing)
        row.save(update_fields=("updated_at",))
    return True


@transaction.atomic
def delete_listing_by_seller(*, listing: Listing, reason: str = "", request=None):
    """Soft-delete a seller-owned listing while retaining moderation/audit history."""
    if listing.seller_deleted_at is not None:
        return listing
    listing.seller_deleted_at = timezone.now()
    listing.seller_delete_reason = (reason or "").strip()[:2000]
    listing.save(
        update_fields=("seller_deleted_at", "seller_delete_reason", "updated_at")
    )
    from audit.services import record_audit_event

    from moderation.models import ModerationCase

    moderation_case_id = None
    moderation_decision = None
    try:
        moderation_case = listing.moderation_case
    except ModerationCase.DoesNotExist:
        moderation_case = None
    if moderation_case is not None and moderation_case.final:
        moderation_case_id = str(moderation_case.id)
        moderation_decision = moderation_case.status

    record_audit_event(
        actor=listing.seller.user,
        action="listing.deleted_by_seller",
        target=listing,
        target_type="listing",
        target_label=listing.title,
        metadata={
            "reason": listing.seller_delete_reason,
            "listing_status_at_delete": listing.status,
            "prior_moderation_case_id": moderation_case_id,
            "prior_moderation_decision": moderation_decision,
        },
        request=request,
    )
    return listing
