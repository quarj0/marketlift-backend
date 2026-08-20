import strawberry


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
    allow_custom_value: bool
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
class DeleteCategoryPayload:
    slug: str
    affected_listings: int


@strawberry.type
class DeleteCategoryFieldPayload:
    category_id: str
    field_id: str
    historical_values: int
    schema_version: int


@strawberry.input
class CategoryAdminInput:
    name: str
    slug: str | None = None
    icon: str | None = None
    description: str | None = None
    parent_id: str | None = None
    active: bool = True
    sort_order: int = 0
    pricing_mode: str = "required"
    pricing_label: str = "Price (R$)"
    pricing_placeholder: str | None = None
    condition_enabled: bool = True
    condition_required: bool = True


@strawberry.input
class CategoryFieldOptionAdminInput:
    label: str
    value: str | None = None
    sort_order: int | None = None


@strawberry.input
class CategoryFieldAdminInput:
    key: str
    label: str
    type: str
    required: bool = False
    filterable: bool = False
    allow_custom_value: bool = False
    placeholder: str | None = None
    help_text: str | None = None
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    sort_order: int = 0
    options: list[CategoryFieldOptionAdminInput] | None = None
