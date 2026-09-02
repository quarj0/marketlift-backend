from uploads.storage import get_storage_backend

from .types import (
    CategoryConditionType,
    CategoryFieldDefinitionType,
    CategoryFieldOptionType,
    CategoryPricingType,
    CategorySummaryType,
    CategoryType,
)


def _category_image_url(category) -> str | None:
    asset = getattr(category, "image_upload", None)
    if asset is None:
        return None
    variant = asset.variants.filter(kind="card").first()
    target = variant or asset
    url = get_storage_backend(target.storage_alias).access_url(target)
    return str(url) if url else target.content_url


def category_to_type(category) -> CategoryType:
    return CategoryType(
        id=category.slug,
        name=category.name,
        icon=category.icon,
        image_url=_category_image_url(category),
        active=category.active,
        schema_version=category.schema_version,
        description=category.description,
        pricing=CategoryPricingType(
            mode=category.pricing_mode,
            label=category.pricing_label,
            placeholder=category.pricing_placeholder or None,
        ),
        condition=CategoryConditionType(
            enabled=category.condition_enabled, required=category.condition_required
        ),
        fields=[
            CategoryFieldDefinitionType(
                id=field.key,
                label=field.label,
                type=field.field_type,
                required=field.required,
                filterable=field.filterable,
                allow_custom_value=field.custom_values_allowed,
                depends_on=field.depends_on.key if field.depends_on_id else None,
                lazy_options=field.lazy_options,
                option_count=sum(1 for option in field.options.all() if option.active),
                placeholder=field.placeholder or None,
                help_text=field.help_text or None,
                unit=field.unit or None,
                min=float(field.min_value) if field.min_value is not None else None,
                max=float(field.max_value) if field.max_value is not None else None,
                step=float(field.step_value) if field.step_value is not None else None,
                options=(
                    []
                    if field.lazy_options or field.depends_on_id
                    else [
                        CategoryFieldOptionType(value=o.value, label=o.label)
                        for o in field.options.all()
                        if o.active
                    ]
                ),
            )
            for field in category.fields.all()
        ],
        subcategories=[
            CategorySummaryType(
                id=c.slug,
                name=c.name,
                icon=c.icon,
                image_url=_category_image_url(c),
                active=c.active,
            )
            for c in category.subcategories.all()
        ],
    )
