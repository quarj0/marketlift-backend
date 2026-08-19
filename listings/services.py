from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from categories.models import Category, CategoryField
from subscriptions.services import get_effective_plan

from .models import Listing, ListingAttribute, ListingMedia


FINAL_STATUSES = {Listing.Status.REJECTED, Listing.Status.REMOVED}
PUBLISHABLE_STATUSES = {
    Listing.Status.DRAFT,
    Listing.Status.PAUSED,
    Listing.Status.EXPIRED,
}
ACTIVE_LIMIT_STATUSES = {Listing.Status.PUBLISHED, Listing.Status.UNDER_REVIEW}


def _validate_scalar(field: CategoryField, value):
    if field.field_type in {CategoryField.FieldType.TEXT, CategoryField.FieldType.TEXTAREA}:
        if not isinstance(value, str):
            raise ValidationError({field.key: f"{field.label} must be text."})
        return value.strip()

    if field.field_type == CategoryField.FieldType.SELECT:
        if not isinstance(value, str):
            raise ValidationError({field.key: f"{field.label} must be a selected value."})
        allowed = set(field.options.values_list("value", flat=True))
        if value not in allowed:
            raise ValidationError({field.key: f"Invalid option for {field.label}."})
        return value

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
            raise ValidationError({field.key: f"{field.label} must be at least {field.min_value}."})
        if field.max_value is not None and number > field.max_value:
            raise ValidationError({field.key: f"{field.label} must be at most {field.max_value}."})
        return number

    raise ValidationError({field.key: f"Unsupported field type: {field.field_type}."})


def validate_listing_payload(*, category: Category, price, condition: str, attributes: dict | None):
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
                errors[key] = messages[0] if isinstance(messages, list) else str(messages)

    if errors:
        raise ValidationError(errors)
    return normalized


def _write_attributes(listing: Listing, normalized: dict[str, tuple[CategoryField, object]]):
    ListingAttribute.objects.filter(listing=listing).exclude(key__in=normalized.keys()).delete()
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


def _write_media(listing: Listing, image_urls: list[str] | None):
    if image_urls is None:
        return
    listing.media.all().delete()
    ListingMedia.objects.bulk_create(
        [
            ListingMedia(
                listing=listing,
                url=url,
                sort_order=index,
                is_primary=index == 0,
            )
            for index, url in enumerate(image_urls)
            if url
        ]
    )


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
    state: str,
    state_code: str,
    city: str,
    district: str = "",
    attributes: dict | None = None,
    image_urls: list[str] | None = None,
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
    listing = Listing.objects.create(
        seller=seller,
        category=category,
        title=title.strip(),
        description=description.strip(),
        price=price,
        condition=condition,
        negotiable=negotiable,
        state=state.strip(),
        state_code=state_code.strip().upper(),
        city=city.strip(),
        district=district.strip(),
    )
    _write_attributes(listing, normalized)
    _write_media(listing, image_urls)
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
    state: str,
    state_code: str,
    city: str,
    district: str = "",
    attributes: dict | None = None,
    image_urls: list[str] | None = None,
):
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
    listing.category = category
    listing.title = title.strip()
    listing.description = description.strip()
    listing.price = price
    listing.condition = condition
    listing.negotiable = negotiable
    listing.state = state.strip()
    listing.state_code = state_code.strip().upper()
    listing.city = city.strip()
    listing.district = district.strip()
    listing.save()
    _write_attributes(listing, normalized)
    _write_media(listing, image_urls)
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
    if listing.seller.is_suspended:
        raise ValidationError("Selling access is suspended.")
    if listing.status == Listing.Status.PUBLISHED:
        return listing
    if listing.status not in PUBLISHABLE_STATUSES:
        raise ValidationError(f"Listing cannot be published from status '{listing.status}'.")
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
    enforce_listing_limit(listing.seller, excluding_listing=listing)

    listing.status = Listing.Status.PUBLISHED
    listing.published_at = timezone.now()
    listing.paused_at = None
    listing.expired_at = None
    listing.save(update_fields=("status", "published_at", "paused_at", "expired_at", "updated_at"))
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
