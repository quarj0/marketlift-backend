from .types import (
    CategoryConditionType,
    CategoryFieldDefinitionType,
    CategoryFieldOptionType,
    CategoryPricingType,
    CategorySummaryType,
    CategoryType,
)


def category_to_type(category) -> CategoryType:
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
                placeholder=field.placeholder or None,
                help_text=field.help_text or None,
                unit=field.unit or None,
                min=float(field.min_value) if field.min_value is not None else None,
                max=float(field.max_value) if field.max_value is not None else None,
                step=float(field.step_value) if field.step_value is not None else None,
                options=[
                    CategoryFieldOptionType(value=o.value, label=o.label)
                    for o in field.options.all()
                ],
            )
            for field in category.fields.all()
        ],
        subcategories=[
            CategorySummaryType(id=c.slug, name=c.name, icon=c.icon, active=c.active)
            for c in category.subcategories.all()
        ],
    )
