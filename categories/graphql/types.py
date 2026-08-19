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


@strawberry.input
class CategoryAdminInput:
    name: str
    slug: str | None = None
    icon: str | None = None
    description: str | None = None
    parent_id: str | None = None
    active: bool = True
    sort_order: int = 0
