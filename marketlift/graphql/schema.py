from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

import strawberry
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from graphql import GraphQLError
from strawberry.scalars import JSON

from categories.models import Category
from listings.models import Listing, SavedListing
from listings.services import (
    create_listing,
    mark_listing_sold,
    pause_listing,
    publish_listing,
    update_listing,
)
from promotions.models import ListingPromotion, PromotionProduct
from sellers.models import SellerProfile
from subscriptions.models import SellerPlan
from subscriptions.services import get_effective_plan


@strawberry.type
class LocationType:
    state: str
    state_code: str
    city: str
    district: str | None = None


@strawberry.type
class CategoryFieldOptionType:
    value: str
    label: str


@strawberry.type
class CategoryFieldDefinitionType:
    id: str
    label: str
    type: str
    required: bool
    filterable: bool
    placeholder: str | None
    help_text: str | None
    unit: str | None
    min: float | None
    max: float | None
    step: float | None
    options: list[CategoryFieldOptionType]


@strawberry.type
class CategoryPricingType:
    mode: str
    label: str
    placeholder: str | None


@strawberry.type
class CategoryConditionType:
    enabled: bool
    required: bool


@strawberry.type
class CategorySummaryType:
    id: str
    name: str
    icon: str
    active: bool


@strawberry.type
class CategoryType:
    id: str
    name: str
    icon: str
    active: bool
    schema_version: int
    description: str
    pricing: CategoryPricingType
    condition: CategoryConditionType
    fields: list[CategoryFieldDefinitionType]
    subcategories: list[CategorySummaryType]


@strawberry.type
class SellerType:
    id: strawberry.ID
    name: str
    verified: bool
    seller_type: str
    is_suspended: bool
    location: LocationType


@strawberry.type
class SellerPlanType:
    id: str
    name: str
    monthly_price: float
    yearly_price: float
    listing_limit: int
    promotion_credits: int
    features: list[str]
    visibility_weight: float
    recommended: bool


@strawberry.type
class PromotionOptionType:
    id: str
    name: str
    description: str
    duration_days: int
    price: float


@strawberry.type
class ListingType:
    id: strawberry.ID
    slug: str
    title: str
    description: str
    price: float | None
    category: str
    category_name: str
    category_schema_version: int
    condition: str | None
    location: LocationType
    images: list[str]
    seller: SellerType
    created_at: datetime
    status: str
    views: int
    negotiable: bool
    attributes: JSON
    featured: bool
    urgent: bool
    favorites: int


@strawberry.type
class DeleteCategoryPayload:
    slug: str
    affected_listings: int


@strawberry.input
class ListingFilterInput:
    q: str | None = None
    category: str | None = None
    state: str | None = None
    city: str | None = None
    district: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    condition: str | None = None
    seller_type: str | None = None
    verified_only: bool = False
    date_listed: str | None = None
    sort: str = "relevant"


@strawberry.input
class ListingInput:
    category_id: str
    title: str
    description: str
    state: str
    state_code: str
    city: str
    price: float | None = None
    condition: str = ""
    district: str = ""
    negotiable: bool = False
    attributes: JSON | None = None
    image_urls: list[str] | None = None


def _request_user(info: strawberry.Info):
    request = getattr(info.context, "request", info.context)
    return getattr(request, "user", None)


def _require_user(info: strawberry.Info):
    user = _request_user(info)
    if not user or not user.is_authenticated:
        raise GraphQLError("Authentication required.")
    return user


def _require_staff(info: strawberry.Info):
    user = _require_user(info)
    if not user.is_staff:
        raise GraphQLError("Admin permission required.")
    return user


def _require_seller(info: strawberry.Info):
    user = _require_user(info)
    try:
        return user.seller_profile
    except SellerProfile.DoesNotExist as exc:
        raise GraphQLError("Activate selling before using seller actions.") from exc


def _decimal(value: float | None):
    return None if value is None else Decimal(str(value))


def _validation_error(exc: ValidationError):
    if hasattr(exc, "message_dict"):
        parts = []
        for field, messages in exc.message_dict.items():
            if not isinstance(messages, (list, tuple)):
                messages = [messages]
            parts.extend(f"{field}: {message}" for message in messages)
        return GraphQLError("; ".join(parts))
    return GraphQLError("; ".join(exc.messages))


def _category_to_type(category: Category) -> CategoryType:
    fields = []
    for field in category.fields.all():
        fields.append(
            CategoryFieldDefinitionType(
                id=field.key,
                label=field.label,
                type=field.field_type,
                required=field.required,
                filterable=field.filterable,
                placeholder=field.placeholder or None,
                help_text=field.help_text or None,
                unit=field.unit or None,
                min=float(field.min_value) if field.min_value is not None else None,
                max=float(field.max_value) if field.max_value is not None else None,
                step=float(field.step_value) if field.step_value is not None else None,
                options=[
                    CategoryFieldOptionType(value=option.value, label=option.label)
                    for option in field.options.all()
                ],
            )
        )

    return CategoryType(
        id=category.slug,
        name=category.name,
        icon=category.icon,
        active=category.active,
        schema_version=category.schema_version,
        description=category.description,
        pricing=CategoryPricingType(
            mode=category.pricing_mode,
            label=category.pricing_label,
            placeholder=category.pricing_placeholder or None,
        ),
        condition=CategoryConditionType(
            enabled=category.condition_enabled,
            required=category.condition_required,
        ),
        fields=fields,
        subcategories=[
            CategorySummaryType(
                id=child.slug,
                name=child.name,
                icon=child.icon,
                active=child.active,
            )
            for child in category.subcategories.all()
        ],
    )


def _seller_to_type(seller: SellerProfile) -> SellerType:
    user = seller.user
    return SellerType(
        id=str(seller.id),
        name=seller.display_name or user.full_name or user.email,
        verified=seller.verified,
        seller_type=seller.seller_type,
        is_suspended=seller.is_suspended,
        location=LocationType(
            state=user.state,
            state_code=user.state_code,
            city=user.city,
            district=user.district or None,
        ),
    )


def _active_promotion_codes(listing: Listing) -> set[str]:
    now = timezone.now()
    if hasattr(listing, "_prefetched_objects_cache") and "promotions" in listing._prefetched_objects_cache:
        return {
            promotion.product.code
            for promotion in listing.promotions.all()
            if promotion.cancelled_at is None and promotion.starts_at <= now < promotion.ends_at
        }
    return set(
        listing.promotions.filter(
            cancelled_at__isnull=True,
            starts_at__lte=now,
            ends_at__gt=now,
        ).values_list("product__code", flat=True)
    )


def _listing_to_type(listing: Listing) -> ListingType:
    attributes = {}
    for item in listing.attribute_values.all():
        value = item.value
        if isinstance(value, Decimal):
            value = float(value)
        attributes[item.key] = value

    codes = _active_promotion_codes(listing)
    return ListingType(
        id=str(listing.id),
        slug=listing.slug,
        title=listing.title,
        description=listing.description,
        price=float(listing.price) if listing.price is not None else None,
        category=listing.category_slug,
        category_name=listing.category_name,
        category_schema_version=listing.category_schema_version,
        condition=listing.condition or None,
        location=LocationType(
            state=listing.state,
            state_code=listing.state_code,
            city=listing.city,
            district=listing.district or None,
        ),
        images=[media.url for media in listing.media.all()],
        seller=_seller_to_type(listing.seller),
        created_at=listing.created_at,
        status=listing.status,
        views=listing.views,
        negotiable=listing.negotiable,
        attributes=attributes,
        featured=PromotionProduct.Code.FEATURED in codes,
        urgent=PromotionProduct.Code.URGENT in codes,
        favorites=listing.saved_by.count(),
    )


def _listing_queryset(queryset=None):
    queryset = queryset if queryset is not None else Listing.objects.all()
    return queryset.select_related("seller__user", "category").prefetch_related(
        "media",
        "attribute_values",
        "promotions__product",
    )


def _owned_listing(info: strawberry.Info, listing_id: strawberry.ID):
    seller = _require_seller(info)
    try:
        listing = _listing_queryset().get(pk=str(listing_id), seller=seller)
    except (Listing.DoesNotExist, ValueError) as exc:
        raise GraphQLError("Listing not found.") from exc
    return listing


@strawberry.type
class Query:
    @strawberry.field
    def health(self) -> str:
        return "ok"

    @strawberry.field
    def categories(self, active_only: bool = True) -> list[CategoryType]:
        queryset = Category.objects.prefetch_related("fields__options", "subcategories")
        if active_only:
            queryset = queryset.filter(active=True)
        return [_category_to_type(item) for item in queryset]

    @strawberry.field
    def category(self, id: str) -> CategoryType | None:
        try:
            item = Category.objects.prefetch_related("fields__options", "subcategories").get(slug=id)
        except Category.DoesNotExist:
            return None
        return _category_to_type(item)

    @strawberry.field
    def listings(
        self,
        filters: ListingFilterInput | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ListingType]:
        filters = filters or ListingFilterInput()
        queryset = _listing_queryset(Listing.objects.public())

        if filters.q:
            queryset = queryset.filter(Q(title__icontains=filters.q) | Q(description__icontains=filters.q))
        if filters.category:
            queryset = queryset.filter(category__slug=filters.category)
        if filters.state:
            queryset = queryset.filter(state_code__iexact=filters.state)
        if filters.city:
            queryset = queryset.filter(city__iexact=filters.city)
        if filters.district:
            queryset = queryset.filter(district__icontains=filters.district)
        if filters.condition:
            queryset = queryset.filter(condition=filters.condition)
        if filters.seller_type:
            queryset = queryset.filter(seller__seller_type=filters.seller_type)
        if filters.verified_only:
            queryset = queryset.filter(seller__verified_at__isnull=False)
        if filters.min_price is not None:
            queryset = queryset.filter(price__gte=_decimal(filters.min_price))
        if filters.max_price is not None:
            queryset = queryset.filter(price__lte=_decimal(filters.max_price))
        if filters.date_listed:
            days = {"today": 1, "week": 7, "month": 30}.get(filters.date_listed)
            if days:
                queryset = queryset.filter(created_at__gte=timezone.now() - timedelta(days=days))

        if filters.sort == "price_asc":
            queryset = queryset.order_by("price", "-created_at")
        elif filters.sort == "price_desc":
            queryset = queryset.order_by("-price", "-created_at")
        elif filters.sort == "newest":
            queryset = queryset.order_by("-created_at")
        else:
            now = timezone.now()
            featured = ListingPromotion.objects.filter(
                listing_id=OuterRef("pk"),
                product__code=PromotionProduct.Code.FEATURED,
                cancelled_at__isnull=True,
                starts_at__lte=now,
                ends_at__gt=now,
            )
            queryset = queryset.annotate(is_featured=Exists(featured)).order_by(
                "-is_featured", "-views", "-created_at"
            )

        safe_limit = max(1, min(limit, 100))
        safe_offset = max(0, offset)
        return [_listing_to_type(item) for item in queryset[safe_offset : safe_offset + safe_limit]]

    @strawberry.field
    def listing(self, id: str) -> ListingType | None:
        queryset = _listing_queryset(Listing.objects.public())
        try:
            if _looks_like_uuid(id):
                item = queryset.get(pk=id)
            else:
                item = queryset.get(slug=id)
        except Listing.DoesNotExist:
            return None
        return _listing_to_type(item)

    @strawberry.field
    def featured_listings(self, limit: int = 8) -> list[ListingType]:
        now = timezone.now()
        queryset = _listing_queryset(Listing.objects.public()).filter(
            promotions__product__code=PromotionProduct.Code.FEATURED,
            promotions__cancelled_at__isnull=True,
            promotions__starts_at__lte=now,
            promotions__ends_at__gt=now,
        ).distinct().order_by("-promotions__starts_at", "-created_at")
        return [_listing_to_type(item) for item in queryset[: max(1, min(limit, 50))]]

    @strawberry.field
    def seller_plans(self) -> list[SellerPlanType]:
        return [
            SellerPlanType(
                id=plan.code,
                name=plan.name,
                monthly_price=float(plan.monthly_price),
                yearly_price=float(plan.yearly_price),
                listing_limit=plan.listing_limit,
                promotion_credits=plan.promotion_credits,
                features=list(plan.features),
                visibility_weight=float(plan.visibility_weight),
                recommended=plan.recommended,
            )
            for plan in SellerPlan.objects.filter(active=True)
        ]

    @strawberry.field
    def promotion_options(self) -> list[PromotionOptionType]:
        return [
            PromotionOptionType(
                id=product.code,
                name=product.name,
                description=product.description,
                duration_days=product.duration_days,
                price=float(product.price),
            )
            for product in PromotionProduct.objects.filter(active=True)
        ]

    @strawberry.field
    def my_listings(self, info: strawberry.Info) -> list[ListingType]:
        seller = _require_seller(info)
        return [_listing_to_type(item) for item in _listing_queryset(seller.listings.all())]

    @strawberry.field
    def my_saved_listings(self, info: strawberry.Info) -> list[ListingType]:
        user = _require_user(info)
        queryset = _listing_queryset(Listing.objects.public()).filter(saved_by__user=user)
        return [_listing_to_type(item) for item in queryset]

    @strawberry.field
    def my_seller_plan(self, info: strawberry.Info) -> SellerPlanType | None:
        seller = _require_seller(info)
        plan = get_effective_plan(seller)
        if not plan:
            return None
        return SellerPlanType(
            id=plan.code,
            name=plan.name,
            monthly_price=float(plan.monthly_price),
            yearly_price=float(plan.yearly_price),
            listing_limit=plan.listing_limit,
            promotion_credits=plan.promotion_credits,
            features=list(plan.features),
            visibility_weight=float(plan.visibility_weight),
            recommended=plan.recommended,
        )


def _looks_like_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except ValueError:
        return False


@strawberry.type
class Mutation:
    @strawberry.mutation
    def activate_selling(self, info: strawberry.Info, seller_type: str = "individual", display_name: str = "") -> SellerType:
        user = _require_user(info)
        if seller_type not in SellerProfile.SellerType.values:
            raise GraphQLError("Invalid seller type.")
        seller, created = SellerProfile.objects.get_or_create(
            user=user,
            defaults={"seller_type": seller_type, "display_name": display_name.strip()},
        )
        if not created:
            seller.seller_type = seller_type
            if display_name.strip():
                seller.display_name = display_name.strip()
            seller.save(update_fields=("seller_type", "display_name", "updated_at"))
        return _seller_to_type(seller)

    @strawberry.mutation
    def create_listing(self, info: strawberry.Info, input: ListingInput) -> ListingType:
        seller = _require_seller(info)
        try:
            category = Category.objects.prefetch_related("fields__options").get(slug=input.category_id)
            listing = create_listing(
                seller=seller,
                category=category,
                title=input.title,
                description=input.description,
                price=_decimal(input.price),
                condition=input.condition,
                negotiable=input.negotiable,
                state=input.state,
                state_code=input.state_code,
                city=input.city,
                district=input.district,
                attributes=dict(input.attributes or {}),
                image_urls=input.image_urls,
            )
        except Category.DoesNotExist as exc:
            raise GraphQLError("Category not found.") from exc
        except ValidationError as exc:
            raise _validation_error(exc) from exc
        return _listing_to_type(_listing_queryset().get(pk=listing.pk))

    @strawberry.mutation
    def update_listing(self, info: strawberry.Info, listing_id: strawberry.ID, input: ListingInput) -> ListingType:
        listing = _owned_listing(info, listing_id)
        try:
            category = Category.objects.prefetch_related("fields__options").get(slug=input.category_id)
            listing = update_listing(
                listing=listing,
                category=category,
                title=input.title,
                description=input.description,
                price=_decimal(input.price),
                condition=input.condition,
                negotiable=input.negotiable,
                state=input.state,
                state_code=input.state_code,
                city=input.city,
                district=input.district,
                attributes=dict(input.attributes or {}),
                image_urls=input.image_urls,
            )
        except Category.DoesNotExist as exc:
            raise GraphQLError("Category not found.") from exc
        except ValidationError as exc:
            raise _validation_error(exc) from exc
        return _listing_to_type(_listing_queryset().get(pk=listing.pk))

    @strawberry.mutation
    def publish_listing(self, info: strawberry.Info, listing_id: strawberry.ID) -> ListingType:
        listing = _owned_listing(info, listing_id)
        try:
            listing = publish_listing(listing)
        except ValidationError as exc:
            raise _validation_error(exc) from exc
        return _listing_to_type(_listing_queryset().get(pk=listing.pk))

    @strawberry.mutation
    def pause_listing(self, info: strawberry.Info, listing_id: strawberry.ID) -> ListingType:
        listing = _owned_listing(info, listing_id)
        try:
            listing = pause_listing(listing)
        except ValidationError as exc:
            raise _validation_error(exc) from exc
        return _listing_to_type(_listing_queryset().get(pk=listing.pk))

    @strawberry.mutation
    def mark_listing_sold(self, info: strawberry.Info, listing_id: strawberry.ID) -> ListingType:
        listing = _owned_listing(info, listing_id)
        try:
            listing = mark_listing_sold(listing)
        except ValidationError as exc:
            raise _validation_error(exc) from exc
        return _listing_to_type(_listing_queryset().get(pk=listing.pk))

    @strawberry.mutation
    def save_listing(self, info: strawberry.Info, listing_id: strawberry.ID) -> bool:
        user = _require_user(info)
        try:
            listing = Listing.objects.public().get(pk=str(listing_id))
        except (Listing.DoesNotExist, ValueError) as exc:
            raise GraphQLError("Listing not found.") from exc
        SavedListing.objects.get_or_create(user=user, listing=listing)
        return True

    @strawberry.mutation
    def unsave_listing(self, info: strawberry.Info, listing_id: strawberry.ID) -> bool:
        user = _require_user(info)
        SavedListing.objects.filter(user=user, listing_id=str(listing_id)).delete()
        return True

    @strawberry.mutation
    def set_category_active(self, info: strawberry.Info, category_id: str, active: bool) -> CategoryType:
        _require_staff(info)
        try:
            category = Category.objects.prefetch_related("fields__options", "subcategories").get(slug=category_id)
        except Category.DoesNotExist as exc:
            raise GraphQLError("Category not found.") from exc
        category.active = active
        category.save(update_fields=("active", "updated_at"))
        return _category_to_type(category)

    @strawberry.mutation
    def delete_category(self, info: strawberry.Info, category_id: str) -> DeleteCategoryPayload:
        _require_staff(info)
        try:
            category = Category.objects.get(slug=category_id)
        except Category.DoesNotExist as exc:
            raise GraphQLError("Category not found.") from exc
        affected = category.listings.count()
        slug = category.slug
        category.delete()
        return DeleteCategoryPayload(slug=slug, affected_listings=affected)


schema = strawberry.Schema(query=Query, mutation=Mutation)
