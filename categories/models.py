from django.core.exceptions import ValidationError
from django.db import models

from marketlift.common.models import UUIDTimeStampedModel
from marketlift.markets.defaults import default_pricing_label


class Category(UUIDTimeStampedModel):
    class PricingMode(models.TextChoices):
        REQUIRED = "required", "Required"
        OPTIONAL = "optional", "Optional"

    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="subcategories",
    )
    slug = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=120)
    icon = models.CharField(max_length=80, blank=True)
    image_upload = models.ForeignKey(
        "uploads.UploadAsset",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="category_visuals",
    )
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    schema_version = models.PositiveIntegerField(default=1)
    pricing_mode = models.CharField(
        max_length=12,
        choices=PricingMode.choices,
        default=PricingMode.REQUIRED,
    )
    pricing_label = models.CharField(max_length=120, default=default_pricing_label)
    pricing_placeholder = models.CharField(max_length=120, blank=True)
    condition_enabled = models.BooleanField(default=True)
    condition_required = models.BooleanField(default=True)

    class Meta:
        ordering = ("sort_order", "name")
        verbose_name_plural = "categories"

    def clean(self):
        super().clean()
        if self.condition_required and not self.condition_enabled:
            raise ValidationError(
                {"condition_required": "A disabled condition cannot be required."}
            )
        if self.parent_id and self.parent_id == self.id:
            raise ValidationError({"parent": "A category cannot be its own parent."})

    def __str__(self) -> str:
        return self.name


class CategoryField(UUIDTimeStampedModel):
    class FieldType(models.TextChoices):
        TEXT = "text", "Text"
        TEXTAREA = "textarea", "Textarea"
        NUMBER = "number", "Number"
        SELECT = "select", "Select"
        BOOLEAN = "boolean", "Boolean"

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="fields",
    )
    key = models.SlugField(max_length=80)
    label = models.CharField(max_length=120)
    field_type = models.CharField(max_length=16, choices=FieldType.choices)
    required = models.BooleanField(default=False)
    filterable = models.BooleanField(default=False)
    # For SELECT fields, options are strict by default. When enabled, options
    # become suggestions and sellers may submit another non-empty scalar value.
    allow_custom_value = models.BooleanField(default=False)
    depends_on = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="dependent_fields",
    )
    lazy_options = models.BooleanField(default=False)
    placeholder = models.CharField(max_length=200, blank=True)
    help_text = models.TextField(blank=True)
    unit = models.CharField(max_length=32, blank=True)
    min_value = models.DecimalField(
        max_digits=16, decimal_places=4, null=True, blank=True
    )
    max_value = models.DecimalField(
        max_digits=16, decimal_places=4, null=True, blank=True
    )
    step_value = models.DecimalField(
        max_digits=16, decimal_places=4, null=True, blank=True
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "label")
        constraints = [
            models.UniqueConstraint(
                fields=("category", "key"),
                name="categories_unique_field_key",
            )
        ]

    def clean(self):
        super().clean()
        if (
            self.min_value is not None
            and self.max_value is not None
            and self.min_value > self.max_value
        ):
            raise ValidationError(
                {"max_value": "Maximum must be greater than minimum."}
            )
        if self.depends_on_id:
            if self.depends_on.category_id != self.category_id:
                raise ValidationError(
                    {"depends_on": "Dependent fields must belong to the same category."}
                )
            if self.depends_on_id == self.id:
                raise ValidationError({"depends_on": "A field cannot depend on itself."})
            if self.field_type != self.FieldType.SELECT:
                raise ValidationError(
                    {"depends_on": "Only choice fields can depend on another answer."}
                )
            if self.depends_on.field_type != self.FieldType.SELECT:
                raise ValidationError(
                    {"depends_on": "The parent answer must also be a choice field."}
                )

    @property
    def custom_values_allowed(self) -> bool:
        # Text/textarea/number inputs are inherently free-form. The flag only
        # changes SELECT semantics from strict choices to suggestions + custom.
        return self.field_type != self.FieldType.SELECT or self.allow_custom_value

    def __str__(self) -> str:
        return f"{self.category.slug}.{self.key}"


class CategoryFieldOption(UUIDTimeStampedModel):
    field = models.ForeignKey(
        CategoryField,
        on_delete=models.CASCADE,
        related_name="options",
    )
    value = models.CharField(max_length=120)
    label = models.CharField(max_length=120)
    active = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "label")
        constraints = [
            models.UniqueConstraint(
                fields=("field", "value"),
                name="categories_unique_option_value",
            )
        ]

    def __str__(self) -> str:
        return f"{self.field}: {self.label}"


class CategoryFieldOptionDependency(UUIDTimeStampedModel):
    option = models.ForeignKey(
        CategoryFieldOption,
        on_delete=models.CASCADE,
        related_name="allowed_parent_links",
    )
    parent_option = models.ForeignKey(
        CategoryFieldOption,
        on_delete=models.CASCADE,
        related_name="child_option_links",
    )

    class Meta:
        ordering = ("option_id", "parent_option_id")
        constraints = [
            models.UniqueConstraint(
                fields=("option", "parent_option"),
                name="categories_unique_option_parent",
            )
        ]

    def clean(self):
        super().clean()
        if self.option_id and self.parent_option_id:
            if self.option.field_id == self.parent_option.field_id:
                raise ValidationError(
                    {"parent_option": "A dependent option must belong to the parent field."}
                )
            expected = self.option.field.depends_on_id
            if expected and self.parent_option.field_id != expected:
                raise ValidationError(
                    {"parent_option": "Parent option belongs to the wrong field."}
                )

    def __str__(self) -> str:
        return f"{self.parent_option} -> {self.option}"
